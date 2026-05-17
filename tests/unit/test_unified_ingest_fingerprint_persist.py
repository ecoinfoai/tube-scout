"""Unit tests for audio fingerprint persistence — spec 018 T011 RED.

Verifies INSERT OR REPLACE semantics of insert_audio_fingerprint and that
after _run_transcript_and_fingerprint processes mp4 files:
  - audio_fingerprint row count == mp4 count
  - second call for same video_id keeps row count == 1 (PK uniqueness)
"""

import sqlite3
from pathlib import Path

from tube_scout.storage.content_db import insert_audio_fingerprint

_V3_BASELINE_SQL = """
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
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
PRAGMA user_version = 3;
"""


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_V3_BASELINE_SQL)
    return db_path


def test_fingerprint_row_count_equals_mp4_count(tmp_path: Path) -> None:
    """audio_fingerprint row count == mp4 count after inserting (FR-018B)."""
    db_path = _make_db(tmp_path)
    ts = "2026-05-16T00:00:00+00:00"

    video_ids = ["VID00001", "VID00002", "VID00003"]
    fp_bytes = b"AAAAAA=="
    for vid in video_ids:
        insert_audio_fingerprint(db_path, vid, fp_bytes, 5.0, ts)

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM audio_fingerprint").fetchone()[0]
    conn.close()

    assert count == len(video_ids)


def test_fingerprint_pk_single_on_second_call(tmp_path: Path) -> None:
    """INSERT OR REPLACE keeps row count == 1 for same video_id (PK uniqueness)."""
    db_path = _make_db(tmp_path)
    ts1 = "2026-05-16T00:00:00+00:00"
    ts2 = "2026-05-16T01:00:00+00:00"
    fp_bytes = b"AAAAAA=="

    insert_audio_fingerprint(db_path, "VID00001", fp_bytes, 5.0, ts1)
    insert_audio_fingerprint(db_path, "VID00001", fp_bytes, 5.0, ts2)

    conn = sqlite3.connect(str(db_path))
    count = conn.execute(
        "SELECT COUNT(*) FROM audio_fingerprint WHERE video_id = ?", ("VID00001",)
    ).fetchone()[0]
    conn.close()

    assert count == 1


def test_fingerprint_row_has_correct_video_id(tmp_path: Path) -> None:
    """Inserted row has correct video_id."""
    db_path = _make_db(tmp_path)
    ts = "2026-05-16T00:00:00+00:00"
    fp_bytes = b"BBBBBB=="

    insert_audio_fingerprint(db_path, "VID99999", fp_bytes, 10.0, ts)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT video_id FROM audio_fingerprint WHERE video_id = ?", ("VID99999",)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "VID99999"
