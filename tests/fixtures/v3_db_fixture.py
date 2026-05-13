"""Reusable v3_db pytest fixture (spec 013 T024).

Provides a pytest fixture that constructs a content_reuse.db at v3 schema
(spec 012 baseline) with representative sample rows. Used by v4 migration
tests (T007 already inlines its own fixture — this is for follow-on tasks
needing v3 sample data).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


_V3_BASELINE_SQL = """
-- spec 007 + 012 baseline tables (minimal columns for testing)
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

CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
"""


@pytest.fixture
def v3_db_with_sample_rows(tmp_path: Path) -> Path:
    """Construct a v3-schema content_reuse.db with representative sample rows.

    Schema: spec 007 (processing_status, quality_results, comparison_results)
    + spec 012 (audio_fingerprint).
    Sample data:
        - 9 audio_fingerprint rows (vidA-vidI, fake 64-byte BLOBs).
        - 3 processing_status rows (vidA collected, vidB pending, vidC failed).
        - 2 comparison_results rows (vidA-vidB pair, vidB-vidC pair).
    PRAGMA user_version = 3.

    Returns:
        Path to the constructed v3 SQLite database file.
    """
    db_path = tmp_path / "v3_sample.db"
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.executescript(_V3_BASELINE_SQL)
        # 9 audio_fingerprint rows
        for i, vid in enumerate("ABCDEFGHI"):
            video_id = f"vid{vid}"
            cur.execute(
                "INSERT INTO audio_fingerprint VALUES (?, ?, ?, ?, ?);",
                (video_id, b"\x00" * 64 + bytes([i]), 100.0 + i, "2026-04-01T09:00:00Z", "fpcalc:1.6.0"),
            )
        # 3 processing_status rows
        cur.execute("INSERT INTO processing_status VALUES ('vidA', 'chA', 'collected', 'whisper', NULL, '2026-04-01T09:00:00Z', NULL, '2026-04-01T09:00:00Z');")
        cur.execute("INSERT INTO processing_status VALUES ('vidB', 'chA', 'pending', NULL, NULL, NULL, NULL, '2026-04-01T09:00:00Z');")
        cur.execute("INSERT INTO processing_status VALUES ('vidC', 'chA', 'failed', NULL, 'ASR error', NULL, NULL, '2026-04-01T09:00:00Z');")
        # 2 comparison_results rows
        cur.execute(
            "INSERT INTO comparison_results (source_video_id, target_video_id, professor, course, week, session, year_from, year_to, i2_cosine_similarity, created_at) "
            "VALUES ('vidA', 'vidB', 'profX', 'subj1', 1, 1, 2024, 2025, 0.85, '2026-04-01T09:00:00Z');"
        )
        cur.execute(
            "INSERT INTO comparison_results (source_video_id, target_video_id, professor, course, week, session, year_from, year_to, i2_cosine_similarity, created_at) "
            "VALUES ('vidB', 'vidC', 'profX', 'subj1', 1, 2, 2024, 2025, 0.42, '2026-04-01T09:00:00Z');"
        )
        cur.execute("PRAGMA user_version = 3;")
        conn.commit()
    return db_path
