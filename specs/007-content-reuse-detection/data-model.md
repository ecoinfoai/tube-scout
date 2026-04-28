# Data Model: Lecture Video Content Reuse Detection

## Entities

### ProcessingStatus

Tracks per-video pipeline progress for resume capability.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string (PK) | YouTube video ID |
| channel_id | string | Channel the video belongs to |
| status | enum | pending, collecting, collected, fingerprinted, compared, failed, no_caption |
| caption_source | enum | transcript_api, captions_api, whisper, null |
| error_message | string (nullable) | Last error if status is failed |
| collected_at | datetime (nullable) | When caption was collected |
| fingerprinted_at | datetime (nullable) | When fingerprint was generated |
| updated_at | datetime | Last status change |

**State transitions**: pending → collecting → collected → fingerprinted → compared. Failed/no_caption are terminal states resettable by force-refresh.

### CaptionFingerprint

SHA-256 hash and embedding reference for each video's caption text.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string (PK) | YouTube video ID |
| sha256_hash | string | SHA-256 hex digest of full caption text |
| full_text_length | integer | Character count of full caption text |
| embedding_row_index | integer | Row index in embeddings.parquet |
| created_at | datetime | When fingerprint was generated |

**Note**: Embedding vectors are stored in Parquet (not SQLite) for efficient vector operations.

### ComparisonResult

Stores the 5-indicator analysis and review status for each comparison pair.

| Field | Type | Description |
|-------|------|-------------|
| id | integer (PK, auto) | Unique comparison ID |
| source_video_id | string (FK) | Video from year A |
| target_video_id | string (FK) | Video from year B |
| professor | string | Matched professor name |
| course | string | Matched course name |
| week | integer | Matched week number |
| session | integer | Matched session number |
| year_from | integer | Source video year |
| year_to | integer | Target video year |
| i1_hash_match | boolean | I-1: SHA-256 hash identical |
| i2_cosine_similarity | float | I-2: Embedding cosine similarity (0.0-1.0) |
| i3_change_rate | float | I-3: Text change rate (0.0-1.0, 0=identical) |
| i4_new_term_count | integer | I-4: Terms in target not in source |
| i5_duration_diff_seconds | float | I-5: Duration difference in seconds |
| suspicion_score | float | Composite score (0-100) |
| grade | enum | critical, high, moderate, normal |
| review_status | enum | UNREVIEWED, CONFIRMED_DUPLICATE, FALSE_POSITIVE |
| reviewed_at | datetime (nullable) | When review status was set |
| reviewed_by | string (nullable) | Reviewer identifier |
| created_at | datetime | When comparison was performed |

**Unique constraint**: (source_video_id, target_video_id) — one result per pair.

### QualityCheckResult

Per-video quality rule pass/fail results.

| Field | Type | Description |
|-------|------|-------------|
| video_id | string (PK) | YouTube video ID |
| q001_voice_present | boolean | Has extractable captions |
| q002_min_duration | boolean | Duration >= 5 minutes |
| q003_course_relevance | float (nullable) | Proportion of course-related terms (pass if >= 0.10) |
| q004_silence_ratio | float (nullable) | Ratio of inter-segment gaps (pass if < 0.30) |
| q005_speech_density | float (nullable) | Characters per minute (pass if 200-600) |
| pass_count | integer | Number of rules passed (0-5) |
| checked_at | datetime | When quality check was performed |

### EmbeddingStore (Parquet)

Stored in `02_analyze/content/embeddings.parquet` via polars.

| Column | Type | Description |
|--------|------|-------------|
| video_id | string | YouTube video ID |
| embedding | list[float] | 768-dimensional embedding vector |
| model_name | string | Embedding model identifier |
| created_at | datetime | When embedding was generated |

## Relationships

```
ProcessingStatus (video_id)
    ├── 1:1 → CaptionFingerprint (video_id)
    ├── 1:1 → QualityCheckResult (video_id)
    └── 1:N → ComparisonResult (source_video_id OR target_video_id)

ComparisonResult
    ├── N:1 → ProcessingStatus (source_video_id)
    └── N:1 → ProcessingStatus (target_video_id)
```

## SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS processing_status (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    caption_source TEXT,
    error_message TEXT,
    collected_at TEXT,
    fingerprinted_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fingerprint_hashes (
    video_id TEXT PRIMARY KEY,
    sha256_hash TEXT NOT NULL,
    full_text_length INTEGER NOT NULL,
    embedding_row_index INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fp_hash ON fingerprint_hashes(sha256_hash);

CREATE TABLE IF NOT EXISTS comparison_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id TEXT NOT NULL,
    target_video_id TEXT NOT NULL,
    professor TEXT,
    course TEXT,
    week INTEGER,
    session INTEGER,
    year_from INTEGER,
    year_to INTEGER,
    i1_hash_match INTEGER NOT NULL DEFAULT 0,
    i2_cosine_similarity REAL,
    i3_change_rate REAL,
    i4_new_term_count INTEGER,
    i5_duration_diff_seconds REAL,
    suspicion_score REAL,
    grade TEXT,
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED',
    reviewed_at TEXT,
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(source_video_id, target_video_id)
);
CREATE INDEX IF NOT EXISTS idx_cr_grade ON comparison_results(grade);
CREATE INDEX IF NOT EXISTS idx_cr_review ON comparison_results(review_status);

CREATE TABLE IF NOT EXISTS quality_results (
    video_id TEXT PRIMARY KEY,
    q001_voice_present INTEGER NOT NULL DEFAULT 0,
    q002_min_duration INTEGER NOT NULL DEFAULT 0,
    q003_course_relevance REAL,
    q004_silence_ratio REAL,
    q005_speech_density REAL,
    pass_count INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL
);
```
