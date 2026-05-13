"""Shared pytest fixture: v3 content_reuse.db for v4 migration tests.

Provides a reusable ``v3_db`` pytest fixture that creates a temporary
SQLite database at v3 schema (spec 007/011/012 baseline) with deterministic
seed rows. Tests that exercise migrate_to_v4 import this fixture instead of
duplicating the builder locally.

Usage::

    # In conftest.py or test file:
    from tests.fixtures.v3_db_fixture import v3_db  # noqa: F401

    def test_something(v3_db: Path) -> None:
        ...
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_SEED_TS = "2026-01-01T00:00:00+00:00"

_V3_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS processing_status (
    video_id             TEXT PRIMARY KEY,
    channel_id           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    caption_source       TEXT,
    error_message        TEXT,
    collected_at         TEXT,
    fingerprinted_at     TEXT,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fingerprint_hashes (
    video_id             TEXT PRIMARY KEY,
    sha256_hash          TEXT NOT NULL,
    full_text_length     INTEGER NOT NULL,
    embedding_row_index  INTEGER,
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fp_hash ON fingerprint_hashes(sha256_hash);

CREATE TABLE IF NOT EXISTS comparison_results (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id      TEXT NOT NULL,
    target_video_id      TEXT NOT NULL,
    professor            TEXT,
    course               TEXT,
    week                 INTEGER,
    session              INTEGER,
    year_from            INTEGER,
    year_to              INTEGER,
    i1_hash_match        INTEGER NOT NULL DEFAULT 0,
    i2_cosine_similarity REAL,
    i3_change_rate       REAL,
    i4_new_term_count    INTEGER,
    i5_duration_diff_seconds REAL,
    suspicion_score      REAL,
    grade                TEXT,
    review_status        TEXT NOT NULL DEFAULT 'UNREVIEWED',
    reviewed_at          TEXT,
    reviewed_by          TEXT,
    created_at           TEXT NOT NULL,
    UNIQUE(source_video_id, target_video_id)
);
CREATE INDEX IF NOT EXISTS idx_cr_grade  ON comparison_results(grade);
CREATE INDEX IF NOT EXISTS idx_cr_review ON comparison_results(review_status);

CREATE TABLE IF NOT EXISTS quality_results (
    video_id             TEXT PRIMARY KEY,
    q001_voice_present   INTEGER NOT NULL DEFAULT 0,
    q002_min_duration    INTEGER NOT NULL DEFAULT 0,
    q003_course_relevance REAL,
    q004_silence_ratio   REAL,
    q005_speech_density  REAL,
    pass_count           INTEGER NOT NULL DEFAULT 0,
    checked_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id             TEXT PRIMARY KEY,
    fingerprint          BLOB NOT NULL,
    duration             REAL NOT NULL,
    extracted_at         TEXT NOT NULL,
    source               TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
CREATE INDEX IF NOT EXISTS idx_audio_fp_extracted_at
    ON audio_fingerprint(extracted_at);
"""


def build_v3_db(path: Path) -> Path:
    """Create a v3-schema content_reuse.db with deterministic seed rows.

    Schema corresponds to spec 007 + spec 011 v2 + spec 012 v3 (audio_fingerprint).
    PRAGMA user_version is set to 3.

    Seed data:
        - 9 audio_fingerprint rows  (video_id v3_vid_000 .. v3_vid_008)
        - 3 processing_status rows  (v3_vid_000, v3_vid_001, v3_vid_002)
        - 2 comparison_results rows (v3_vid_000 vs v3_vid_001,
                                     v3_vid_001 vs v3_vid_002)

    Args:
        path: Filesystem path for the new SQLite file. Parent dirs are
            created automatically. Overwrites any existing file at ``path``.

    Returns:
        The same ``path`` after the database has been initialised.

    Raises:
        TypeError: If ``path`` is not a Path instance.
    """
    if not isinstance(path, Path):
        raise TypeError(f"path must be a Path, got {type(path).__name__}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    with sqlite3.connect(str(path)) as conn:
        conn.executescript(_V3_SCHEMA_SQL)

        # 9 audio_fingerprint rows — deterministic fake chromaprint BLOBs
        fp_rows = [
            (
                f"v3_vid_{i:03d}",
                f"fakefingerprint{i:048d}".encode(),
                60.0 + i * 10.0,
                _SEED_TS,
                "fpcalc:1.6.0",
            )
            for i in range(9)
        ]
        conn.executemany(
            "INSERT INTO audio_fingerprint "
            "(video_id, fingerprint, duration, extracted_at, source) "
            "VALUES (?, ?, ?, ?, ?)",
            fp_rows,
        )

        # 3 processing_status rows
        ps_rows = [
            ("v3_vid_000", "ch-test", "fingerprinted", "whisper",    None, _SEED_TS, _SEED_TS, _SEED_TS),
            ("v3_vid_001", "ch-test", "fingerprinted", "whisper",    None, _SEED_TS, _SEED_TS, _SEED_TS),
            ("v3_vid_002", "ch-test", "collected",     None,         None, _SEED_TS, None,     _SEED_TS),
        ]
        conn.executemany(
            "INSERT INTO processing_status "
            "(video_id, channel_id, status, caption_source, error_message, "
            " collected_at, fingerprinted_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ps_rows,
        )

        # 2 comparison_results rows
        cr_rows = [
            ("v3_vid_000", "v3_vid_001", "prof-test", "CS101", 1, 1, 2024, 2025,
             0, 0.82, 0.10, 3, 5.0, 0.75, "high", "UNREVIEWED", None, None, _SEED_TS),
            ("v3_vid_001", "v3_vid_002", "prof-test", "CS101", 2, 1, 2024, 2025,
             0, 0.45, 0.35, 8, 12.0, 0.40, "low", "UNREVIEWED", None, None, _SEED_TS),
        ]
        conn.executemany(
            "INSERT INTO comparison_results "
            "(source_video_id, target_video_id, professor, course, week, session, "
            " year_from, year_to, i1_hash_match, i2_cosine_similarity, "
            " i3_change_rate, i4_new_term_count, i5_duration_diff_seconds, "
            " suspicion_score, grade, review_status, reviewed_at, reviewed_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            cr_rows,
        )

        conn.execute("PRAGMA user_version = 3;")

    return path


@pytest.fixture
def v3_db(tmp_path: Path) -> Path:
    """Pytest fixture: temporary v3 content_reuse.db with baseline seed rows.

    Yields:
        Path to a fresh v3-schema SQLite database containing:
        - 9 audio_fingerprint rows
        - 3 processing_status rows
        - 2 comparison_results rows
        - PRAGMA user_version = 3
    """
    return build_v3_db(tmp_path / "content_reuse.db")
