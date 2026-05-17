"""Integration tests — v3→v4 migration (spec 013 T007)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_V3_SCHEMA_SQL = """
PRAGMA user_version = 3;

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

CREATE TABLE IF NOT EXISTS comparison_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id TEXT NOT NULL,
    target_video_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_video_id, target_video_id)
);

CREATE TABLE IF NOT EXISTS quality_results (
    video_id TEXT PRIMARY KEY,
    q001_voice_present INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id TEXT PRIMARY KEY,
    fingerprint_raw TEXT,
    created_at TEXT NOT NULL
);
"""


def _make_v3_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(_V3_SCHEMA_SQL)


def _table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    return {row[0] for row in rows}


def _column_names(path: Path, table: str) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {row[1] for row in rows}


def _user_version(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version;").fetchone()[0]


@pytest.fixture
def v3_db(tmp_path: Path) -> Path:
    db = tmp_path / "content_reuse.db"
    _make_v3_db(db)
    return db


def test_migrate_v3_to_v4_creates_two_new_tables(v3_db: Path) -> None:
    """channel_metadata and video_metadata tables must exist after migration."""
    from tube_scout.storage.content_db import migrate_to_v4

    migrate_to_v4(v3_db)
    tables = _table_names(v3_db)
    assert "channel_metadata" in tables, "channel_metadata table missing after v4 migration"
    assert "video_metadata" in tables, "video_metadata table missing after v4 migration"


def test_migrate_v3_to_v4_adds_7_columns(v3_db: Path) -> None:
    """7 new columns must be added across 3 existing tables."""
    from tube_scout.storage.content_db import migrate_to_v4

    migrate_to_v4(v3_db)

    ps_cols = _column_names(v3_db, "processing_status")
    assert "match_confidence" in ps_cols
    assert "caption_source_detail" in ps_cols

    qr_cols = _column_names(v3_db, "quality_results")
    assert "asr_quality_flags" in qr_cols

    cr_cols = _column_names(v3_db, "comparison_results")
    assert "audio_fp_hamming" in cr_cols
    assert "audio_fp_best_offset" in cr_cols
    assert "audio_fp_overlap_seconds" in cr_cols
    assert "source_type_pair" in cr_cols


def test_migrate_v3_to_v4_preserves_existing_rows(v3_db: Path) -> None:
    """Pre-existing rows in v3 tables must survive migration intact."""
    from tube_scout.storage.content_db import migrate_to_v4

    with sqlite3.connect(v3_db) as conn:
        conn.execute(
            "INSERT INTO processing_status "
            "(video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            ("vid001", "ch001", "done", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO comparison_results "
            "(source_video_id, target_video_id, created_at) VALUES (?, ?, ?)",
            ("vid001", "vid002", "2026-01-01T00:00:00"),
        )

    migrate_to_v4(v3_db)

    with sqlite3.connect(v3_db) as conn:
        ps_rows = conn.execute("SELECT * FROM processing_status;").fetchall()
        cr_rows = conn.execute("SELECT * FROM comparison_results;").fetchall()

    assert len(ps_rows) == 1, "processing_status rows lost after migration"
    assert len(cr_rows) == 1, "comparison_results rows lost after migration"


def test_migrate_idempotent_two_calls(v3_db: Path) -> None:
    """Calling migrate_to_v4 twice must produce identical schema (no error)."""
    from tube_scout.storage.content_db import migrate_to_v4

    migrate_to_v4(v3_db)
    cols_after_first = _column_names(v3_db, "processing_status")

    migrate_to_v4(v3_db)
    cols_after_second = _column_names(v3_db, "processing_status")

    assert cols_after_first == cols_after_second


def test_pragma_user_version_set_to_4(v3_db: Path) -> None:
    """PRAGMA user_version must be 4 after migration."""
    from tube_scout.storage.content_db import migrate_to_v4

    migrate_to_v4(v3_db)
    assert _user_version(v3_db) == 4
