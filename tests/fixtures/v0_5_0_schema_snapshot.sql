-- SQLite v4 schema snapshot from master v0.5.0 (spec 013 final)
-- Used by tests/integration/test_v4_schema_invariant.py to verify B-4 boundary.
-- Format: CREATE TABLE blocks separated by blank lines.
-- user_version = 4

CREATE TABLE channel_metadata (
    channel_id TEXT,
    channel_alias TEXT,
    title TEXT,
    country TEXT,
    privacy_status TEXT,
    source TEXT,
    takeout_root_hint TEXT,
    ingested_at TEXT
);

CREATE TABLE video_metadata (
    video_id TEXT,
    channel_id TEXT,
    title TEXT,
    duration_seconds REAL,
    language TEXT,
    category TEXT,
    privacy_status TEXT,
    created_at TEXT,
    published_at TEXT,
    source TEXT,
    match_confidence TEXT,
    mp4_relative_path TEXT,
    ingested_at TEXT
);

CREATE TABLE processing_status (
    video_id TEXT,
    channel_id TEXT,
    status TEXT,
    caption_source TEXT,
    error_message TEXT,
    collected_at TEXT,
    fingerprinted_at TEXT,
    updated_at TEXT,
    match_confidence TEXT,
    caption_source_detail TEXT
);

CREATE TABLE quality_results (
    video_id TEXT,
    q001_voice_present INTEGER,
    q002_min_duration INTEGER,
    q003_course_relevance REAL,
    q004_silence_ratio REAL,
    q005_speech_density REAL,
    pass_count INTEGER,
    checked_at TEXT,
    asr_quality_flags TEXT
);

CREATE TABLE comparison_results (
    id INTEGER,
    source_video_id TEXT,
    target_video_id TEXT,
    professor TEXT,
    course TEXT,
    week INTEGER,
    session INTEGER,
    year_from INTEGER,
    year_to INTEGER,
    i1_hash_match INTEGER,
    i2_cosine_similarity REAL,
    i3_change_rate REAL,
    i4_new_term_count INTEGER,
    i5_duration_diff_seconds REAL,
    suspicion_score REAL,
    grade TEXT,
    review_status TEXT,
    reviewed_at TEXT,
    reviewed_by TEXT,
    created_at TEXT,
    matching_mode TEXT,
    professor_id TEXT,
    i6_longest_contiguous_seconds REAL,
    i7_distribution_dispersion REAL,
    i8_position_diversity REAL,
    reuse_pattern TEXT,
    layer_attribution TEXT,
    baseline_subtracted_length_seconds REAL,
    pre_subtraction_i2 REAL,
    pre_subtraction_i6 REAL,
    audio_fp_hamming INTEGER,
    audio_fp_best_offset REAL,
    audio_fp_overlap_seconds REAL,
    source_type_pair TEXT
);
