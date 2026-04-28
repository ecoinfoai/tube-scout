# Research: Lecture Video Content Reuse Detection

## R-001: Captions API Integration for Private Videos

**Decision**: Use YouTube Captions API (`captions.list` + `captions.download`) with `youtube.force-ssl` OAuth scope for private video caption access.

**Rationale**: Empirically verified on 2026-04-07. `youtube-transcript-api` cannot access private videos (no OAuth support). Captions API with force-ssl scope successfully listed and downloaded captions from private videos. 99.4% of private videos have ASR captions.

**Alternatives considered**:
- `youtube-transcript-api` only → fails for 88.6% of videos (private)
- yt-dlp + browser cookies → quota-free but cookie management fragile for automation
- Whisper STT → unnecessary for 99.4% of videos that already have ASR

**Key findings**:
- `youtube.force-ssl` is a superset of `youtube.readonly` — all existing read operations continue to work
- `captions.list` costs 50 quota units; `captions.download` costs 200 units (250 total per video)
- SRT format returned; needs parsing to segment format (text + start + duration)
- Scope change requires one-time re-authentication for existing tokens

## R-002: SRT Parsing Strategy

**Decision**: Parse SRT to segment dicts matching existing transcript format `{"text": str, "start": float, "duration": float}`.

**Rationale**: Existing TranscriptService returns this format. Maintaining consistency means all downstream code (fingerprint, quality check) works identically regardless of caption source.

**Alternatives considered**:
- Store SRT files directly → requires separate parsing in every consumer
- Use a third-party SRT parser (pysrt, srt) → extra dependency for trivial format

**Implementation**: Simple regex/state-machine parser for SRT (sequence number, timestamp line `HH:MM:SS,mmm --> HH:MM:SS,mmm`, text lines, blank separator).

## R-003: Embedding Model Selection

**Decision**: `jhgan/ko-sroberta-multitask` via sentence-transformers for Korean-optimized sentence embeddings.

**Rationale**: Primary content is Korean university lectures. This model is specifically trained for Korean semantic similarity tasks. Already referenced in idea4.md and aligns with existing `get_device()` GPU infrastructure from idea3.2.

**Alternatives considered**:
- `paraphrase-multilingual-MiniLM-L12-v2` (used in ytsubs) → good multilingual support but not Korean-optimized
- OpenAI/Anthropic embedding APIs → adds cost and latency; local inference is free
- TF-IDF / bag-of-words → no semantic understanding; misses paraphrased content

**Key details**:
- Model produces 768-dimensional embeddings
- First load: ~2GB download, subsequent loads from cache
- GPU acceleration available via `get_device()` (existing infrastructure)
- Batch encoding supported for efficiency

## R-004: SQLite Schema Design

**Decision**: Single SQLite database per project at `projects/{project}/tube_scout.db` with 4 tables.

**Rationale**: SQLite is zero-config, file-based (matches CLI tool philosophy), supports transactions for state consistency, and provides indexed queries for processing status lookup and comparison result filtering. stdlib (`sqlite3`) — no additional dependency.

**Alternatives considered**:
- JSON files per video → no index, no transaction, O(n) lookup at 2,500+ scale
- PostgreSQL (ytsubs approach) → requires server process, overkill for CLI tool
- LanceDB/ChromaDB → vector-specific DBs unnecessary at 2,500 video scale (brute-force cosine is milliseconds)

**Tables**:
1. `processing_status` — per-video pipeline state tracking
2. `fingerprint_hashes` — SHA-256 index for O(1) hash lookup
3. `comparison_results` — 5 indicators + suspicion score + review status
4. `caption_upload_queue` — future: Whisper→YouTube upload tracking

## R-005: Suspicion Score Calculation

**Decision**: Weighted sum of 5 normalized indicators, each scaled to 0.0-1.0, combined to 0-100 composite score.

**Rationale**: Multiple independent indicators reduce false positives. Weighted combination allows tuning based on indicator reliability (hash match is definitive; duration difference is circumstantial).

**Proposed weights** (tunable):
- I-1 (hash match): 30 — definitive when matched
- I-2 (cosine similarity): 25 — strong semantic signal
- I-3 (text change rate): 20 — complementary to I-2
- I-4 (new term count): 15 — content freshness indicator
- I-5 (duration difference): 10 — weakest signal, easily coincidental

**Normalization**:
- I-1: binary (0 or 1.0)
- I-2: raw cosine similarity (already 0-1)
- I-3: 1.0 - change_rate (invert: low change = high suspicion)
- I-4: 1.0 if 0 new terms, decreasing with more new terms (e.g., `1 / (1 + new_term_count)`)
- I-5: 1.0 if |diff| <= 10s, decreasing (e.g., `max(0, 1 - |diff| / 60)`)

**Grade thresholds**: critical ≥ 80, high ≥ 60, moderate ≥ 40, normal < 40

## R-006: Comparison Pair Matching Strategy

**Decision**: Use existing ParsedTitle data (professor, course, week, session, year) to generate comparison pairs. Match: same professor + course + week + session across consecutive years.

**Rationale**: Title parsing infrastructure from idea3 already extracts these fields. Matching by structured metadata avoids O(n²) all-pairs comparison — only semantically meaningful pairs are compared.

**Edge cases resolved**:
- Parse failures → excluded from comparison, reported separately
- Multiple videos per course×week×year → use latest published_at as representative
- Missing year in one direction → no pair generated, noted in report
- Same course name across departments → professor field disambiguates

## R-007: Incremental Processing Strategy

**Decision**: Per-video processing status in SQLite with states: `pending`, `collecting`, `collected`, `fingerprinted`, `compared`, `failed`, `no_caption`.

**Rationale**: Enables resume from any point after interruption (quota exhaustion, network error, user abort). Incremental collection only processes videos not yet in `collected` or later states.

**State transitions**:
```
pending → collecting → collected → fingerprinted → compared
                    ↘ failed
                    ↘ no_caption
```
