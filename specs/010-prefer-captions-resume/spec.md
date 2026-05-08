# Feature Specification: Captions-First Priority + Skip-Existing Resume for `collect transcripts`

**Feature Branch**: `010-prefer-captions-resume`
**Created**: 2026-05-09
**Status**: Planned (ready for plan + tasks)
**Input**: Operator request following spec 009 close-out and 2026-05-08 IP-block incident on `youtube-transcript-api` during the first multi-video transcript run on the `nursing` alias. The institutional Cloud Project (`tube-scout-prod`, project number `288171040300`) has submitted a YouTube Data API quota extension to ~1M units/day. Once approved, the OAuth Captions API path becomes operationally cheaper and more reliable than scraper. We want the option to skip the IP-block-prone scraper entirely, and we need idempotent resume so that quota-bounded backfills (spread across 5–7 days at 1M units/day) survive interruption.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Captions-API-first priority bypasses scraper for owned channels (Priority: P1)

A department operator with quota-extended OAuth on a channel they own wants `collect transcripts` to fetch captions through the YouTube Data API Captions endpoint as the primary path. The scraper-based `youtube-transcript-api` is unreliable for institutional residential / shared-IP networks (observed `RequestBlocked` on 2026-05-08 mid-run after roughly 21 successful videos), and there is no architectural reason for an institutional operator with channel ownership to depend on it.

**Why this priority**: Without P1, the only available "primary" path is scraper, which has no path forward when YouTube blocks the IP. Operators are forced to wait hours or migrate to a different network. Once quota is approved, the entire scraper dependency can be sidelined for owned-channel work — this story makes that path opt-in via flag.

**Independent Test**: With `--prefer-captions-api` set on a `collect transcripts` invocation against a channel where `youtube-transcript-api` would IP-block, all videos with caption tracks (manual or ASR) on the channel must successfully produce transcript JSON files. The scraper is touched at most as a fallback for the rare case where Captions API returns empty.

**Acceptance Scenarios**:

1. **Given** an operator runs `collect transcripts --channel nursing --prefer-captions-api` and the IP is currently blocked by youtube-transcript-api, **When** the command runs, **Then** every video with a caption track on the channel produces a transcript JSON whose `source` field is `captions_api`. No `RequestBlocked` exception is propagated to the operator output.
2. **Given** a video has no manual caption track but does have an ASR caption track and the operator has `--prefer-captions-api` set, **When** the service fetches the caption, **Then** the Captions API is consulted first; if it returns a valid track (manual or ASR), that result is used and the scraper is NOT called.
3. **Given** a video has neither a manual nor an ASR caption track AND the operator has `--prefer-captions-api` set, **When** the service has exhausted the Captions API path (returns empty), **Then** the scraper is consulted as a fallback. If the scraper succeeds, the JSON is written with `source: auto_generated` (or `manual`). If the scraper also fails, the video is recorded as a miss in the audit CSV with the appropriate classification.
4. **Given** the operator runs the same command **without** `--prefer-captions-api`, **When** the command runs, **Then** behavior is byte-identical to spec-009 master: scraper attempted first, Captions API used only on scraper failure for private videos. (No regression for the default path.)

---

### User Story 2 — Idempotent resume after interruption (Priority: P1)

The same operator runs an institutional backfill of ~10,000 lecture videos across 22 channels. With the requested 1M units/day quota, this completes in 5–7 calendar days. Mid-run interruptions are inevitable: laptop closes, terminal session ends, transient network failure, daily-quota exhaustion. Today, re-running `collect transcripts` re-fetches every video from scratch, wasting both wall-clock time and quota units. The operator wants the command to skip videos whose transcript is already present in the project's collect directory and only fetch the remaining ones.

**Why this priority**: Without P2, a single interruption forces the operator to either rebuild the run from scratch (incurring the entire quota again) or hand-craft a `--video-id` loop. Both are unacceptable for institutional-scale work. P2 makes the command naturally interruption-tolerant.

**Independent Test**: Run `collect transcripts --channel <alias>` partially (e.g., kill it mid-run after 100/2554 transcripts). Re-run the same command without `--force-refresh`. The second run must skip the 100 already-collected videos (logging each as `cached`) and proceed to fetch the remaining 2454. The total wall-clock time of the second run for the cached portion must be on the order of seconds (file existence checks only — no network calls).

**Acceptance Scenarios**:

1. **Given** a project directory contains `01_collect/transcripts/private_vid_001.json` with `{"video_id": "private_vid_001", "segments": [...non-empty...]}`, **When** `collect transcripts --channel <alias>` runs (without `--force-refresh`), **Then** `private_vid_001` is logged once as `cached (N segments)` (single dim line), no API call is made for it, and audit CSV (if emitted) classifies the video as `skipped`.
2. **Given** the operator passes `--force-refresh`, **When** the command runs, **Then** the cache is ignored: every video is re-fetched, and existing transcript JSON files are atomically overwritten with the fresh result. (This matches the existing `--force-refresh` semantics on `collect videos`.)
3. **Given** an existing transcript JSON file is present but is corrupt (invalid JSON, truncated, or missing the `segments` key), **When** the command runs (without `--force-refresh`), **Then** the corrupt file is treated as if it did not exist: the video is re-fetched and the file is overwritten with the valid result. The operator is not asked to manually delete corrupt files.
4. **Given** an existing transcript JSON file is present but has an empty `segments` array (`{"segments": []}`), **When** the command runs (without `--force-refresh`), **Then** the empty file is treated as if it did not exist: re-fetch occurs. (Empty segments indicate a previous failed-but-written record; not authoritative.)
5. **Given** the operator passes both `--prefer-captions-api` and runs a partial-then-resume sequence, **When** the second run starts, **Then** skip-existing applies BEFORE the prefer-captions-api branch: cached files are skipped without consulting either path.
6. **Given** the operator passes `--video-id <single-vid>` with a cached file present (no `--force-refresh`), **When** the command runs, **Then** the single-video request still respects the cache and prints `cached (N segments)` instead of re-fetching. (Operators use `--force-refresh` to override.)

---

### User Story 3 — Audit CSV records the `skipped` category (Priority: P2)

The operational diagnostic CSV (`<project>/01_collect/transcripts_audit.csv`, introduced in spec 009 FR-016) currently records only misses (videos with no transcript). For institutional reporting and long-running backfills, the operator also wants to know which videos were skipped because of the cache — both for traceability ("did the resume skip what I expected?") and for accurate per-day quota accounting.

**Why this priority**: P2 because the underlying behavior (skip on cache hit) is delivered by Story 2. Story 3 only extends the audit artifact to expose what was skipped. Without it, the operator can still inspect the `transcripts/` directory directly to see which JSONs exist; with it, a single CSV captures the full triage.

**Independent Test**: Run two consecutive `collect transcripts` invocations on a partial channel. The audit CSV after the second run includes one row per cached video with `classification = skipped` and a hint that explains the cache-hit reason.

**Acceptance Scenarios**:

1. **Given** 100 videos are cached (existing valid transcript JSONs) and 50 remain to be fetched, **When** the command runs successfully, **Then** the audit CSV emitted at the end of the run contains 100 rows with `classification=skipped`, plus rows for any of the 50 fetches that resulted in misses. Successfully fetched videos do not produce audit rows (only misses + skips).
2. **Given** a cached video is skipped, **When** the audit row is written, **Then** the `hint` column reads similar to `Existing transcript at <path>; pass --force-refresh to override.` so operators have a copy-pasteable next step.
3. **Given** the operator passes `--force-refresh`, **When** the command runs, **Then** no `skipped` rows are emitted (because nothing is skipped).

---

## Functional Requirements *(mandatory)*

### FR-010-01 — `--prefer-captions-api` CLI flag
`tube-scout collect transcripts` accepts an optional `--prefer-captions-api` boolean flag (default `False`). When set, `TranscriptService.fetch_transcript()` consults the Captions API path first.

### FR-010-02 — `--force-refresh` extended to `collect transcripts`
The existing `--force-refresh` flag (currently on `collect videos`) is extended to `collect transcripts` with identical semantics: ignore cache, re-fetch everything, overwrite existing files atomically.

### FR-010-03 — Captions-API-first priority order in `fetch_transcript`
When `prefer_captions_api=True` is passed to `TranscriptService.fetch_transcript()`, the method calls `self._captions_client.fetch_segments(video_id)` first. If that returns a non-empty segment list, it is used. If it returns `None` or an empty list, the method falls back to the existing primary scraper path (`self._api.list(video_id)`). The default (`prefer_captions_api=False`) preserves the spec-009 order verbatim.

### FR-010-04 — Skip-existing logic in `collect_transcripts_command`
Before calling `service.fetch_transcript(vid_id, ...)`, the orchestrator checks whether `<project>/01_collect/transcripts/<vid_id>.json` exists. If yes, it reads the file, validates that the JSON is well-formed and `segments` is a non-empty list, and on success: (a) prints a single dim `<vid_id>: cached (N segments)` line, (b) appends a `skipped` audit row, (c) advances to the next video without calling the service. If the file is missing, corrupt, or has empty `segments`, it falls through to the service call as if no cache existed.

### FR-010-05 — `--force-refresh` overrides skip-existing
When `--force-refresh` is set, the orchestrator does NOT consult the cache and calls the service for every video. Existing transcript JSONs are atomically overwritten on success. No `skipped` audit rows are emitted.

### FR-010-06 — `skipped` classification in `transcripts_audit.py`
`ALLOWED_CLASSIFICATIONS` (`src/tube_scout/services/transcripts_audit.py:39`) gains a new value `"skipped"`. `classify_miss()` is NOT the right entry point for skipped rows (because `classify_miss` is invoked on actual misses); instead, the orchestrator constructs `skipped` audit rows directly inline when it decides to skip a cached video. The audit row format (header columns) is unchanged: `(video_id, title, published_at, privacy_status, classification, hint)`. The `hint` for a skipped row is a fixed-format human-readable string referencing the cached path.

### FR-010-07 — Backward compatibility (default behavior unchanged)
With both flags off (`--prefer-captions-api=False`, `--force-refresh=False`) and an empty `transcripts/` directory, `collect transcripts` produces byte-identical output to spec-009 master. All existing spec-009 contract and integration tests must remain green.

### FR-010-08 — Atomic write of transcript JSONs
On a re-fetch (whether `--force-refresh` or because the previous file was corrupt), the new JSON is written atomically (write to temp file in same directory + `os.replace`). A SIGINT mid-write must not leave a half-written file in a state where skip-existing would later treat it as valid.

---

## Edge Cases *(mandatory)*

| ID | Scenario | Expected Behavior |
|---|---|---|
| EC-010-A | Existing transcript JSON has malformed JSON (truncated by SIGKILL during prior run) | Silently re-fetch; overwrite atomically. No operator-visible error. |
| EC-010-B | Existing transcript JSON parses but lacks `segments` key entirely | Treat as missing; re-fetch and overwrite. |
| EC-010-C | Existing transcript JSON has `"segments": []` (zero-length list) | Treat as missing; re-fetch and overwrite. |
| EC-010-D | `--prefer-captions-api` with no Captions API client (e.g., auth missing) | Print warning identical to spec-009 ("Captions API fallback unavailable: <reason>"), then run scraper-only. No silent crash. |
| EC-010-E | `--prefer-captions-api` AND `--force-refresh` together | Both flags compose: re-fetch everything, but consult Captions API first for each. |
| EC-010-F | Captions API returns track but `download_caption()` returns 0-segment SRT | Treat as empty; fall through to scraper if `--prefer-captions-api`, else fall through per default order. |
| EC-010-G | `<vid_id>.json` exists but is a directory (operator error or filesystem corruption) | Re-fetch and atomically replace; if replace fails, fail the single video with classification `api_error` and a hint pointing the operator at filesystem inspection. Other videos in the run continue. |
| EC-010-H | `--video-id <vid>` with cached file and no `--force-refresh` | Print `cached (N segments)`; emit one `skipped` row in audit CSV. Same behavior as bulk mode for the single video. |
| EC-010-I | Quota exhausted mid-run with `--prefer-captions-api` | Captions API raises `HttpError 403 quotaExceeded`; service treats as "Captions API empty" and falls through to scraper for that video; subsequent videos keep trying Captions API (each call consumes quota; transient quota recovery is possible across day boundary, but within-run, repeated 403s simply route everything to scraper). |
| EC-010-J | Concurrent runs of `collect transcripts` on same project (operator footgun) | Not formally guarded. Each writes atomically to its own video's file, so no half-write; both may "win" the same video (rare), but the result is the same SRT. Operators are advised in `quickstart.md` not to run two concurrent transcript collectors on one project. |

---

## Acceptance Criteria *(mandatory — measurable)*

A1. `tube-scout collect transcripts --help` lists `--prefer-captions-api` and `--force-refresh` flags.

A2. With an empty `transcripts/` directory and both flags off, `pytest tests/contract/test_collect_transcripts*.py tests/integration/test_collect_chain.py` is green (no spec-009 regression).

A3. Unit tests cover the priority-inversion logic in `TranscriptService.fetch_transcript()` for both `prefer_captions_api={False, True}` × `{captions returns segments, captions returns empty, captions raises}`.

A4. Integration test demonstrates a partial-then-resume run that skips cached videos on the second invocation. Wall-clock for the cached portion is bounded (≤ 0.05 s/video including audit-row construction).

A5. Adversary suite (`tests/adversary/test_transcripts_resume.py`) covers ≥ 8 personas: corrupt cache, empty segments, malformed file as directory, --force-refresh consistency, atomic-write under SIGINT, audit CSV correctness for skipped, --prefer-captions-api with quota-exhausted, --prefer-captions-api with empty captions API, regression-of-default, silent-skip detector (orchestrator forgets to pass flag).

A6. `transcripts_audit.csv` after a resume run includes one row per skipped video with `classification=skipped` and a hint referencing the cached path.

A7. `ruff check .` is clean. `pytest tests/` reports >= 1956 + new tests passing, 0 failing.

A8. The change adds NO new third-party dependency.

---

## Output Format — Audit CSV `skipped` row *(mandatory)*

The CSV header is unchanged. A skipped row has the form:

```csv
video_id,title,published_at,privacy_status,classification,hint
private_vid_001,Sample Lecture Week 13,2026-04-06T07:24:13Z,unlisted,skipped,Existing transcript at projects/<ts>/01_collect/transcripts/private_vid_001.json (5 segments); pass --force-refresh to override.
```

The hint includes (a) the absolute or project-relative path to the cached file and (b) the segment count, so an operator can quickly verify the cache contents without opening the JSON.

---

## Out of Scope *(non-goals)*

- O1. **Cache invalidation by transcript-content TTL**: cached transcripts never expire on time. Operator passes `--force-refresh` when needed.
- O2. **Partial cache reconciliation against video metadata**: if `videos_meta.json` lists 2,554 videos but the `transcripts/` directory has 100 unrelated JSONs from a different channel, this spec does not detect or warn. Operators are expected to keep one project per channel.
- O3. **Multiple-language caption selection at the cache layer**: skip-existing checks file presence + segments, not language. Language preference is already handled inside `CaptionsAPIClient._select_best_track()` and applies on every fetch — once a language is chosen and cached, future runs reuse it.
- O4. **Concurrent-run locking**: this spec does not introduce a `flock`-based guard against two simultaneous `collect transcripts` invocations on the same project. Atomic per-video write is the only concurrency safeguard.
- O5. **Distributed cache / remote cache**: cache is strictly per-machine, per-project-directory. No S3/GCS/redis backing.
- O6. **Removal of `youtube-transcript-api` as a dependency**: even though `--prefer-captions-api` makes scraper optional, the dependency stays for default-path users. Removal is a follow-up after broad operator validation.

---

## Non-Functional Requirements

- NFR-1. Skip-existing check overhead: <= 0.05 s/video on a typical SSD-backed Linux. (File `os.stat` + JSON read of a small file.)
- NFR-2. No new dependencies introduced.
- NFR-3. New code paths covered by unit tests at >= 90% line coverage, measured on the 3 source files only (collect.py, transcript.py, transcripts_audit.py).
- NFR-4. Anonymized fixtures only — `홍길동` / `김영희` / `private_vid_001..N` / `public_vid_001..N`. No real names or real video IDs.
