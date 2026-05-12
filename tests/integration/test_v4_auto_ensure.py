"""Integration tests — _ensure_v4 auto-migration (spec 013 T008)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


_V3_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS processing_status (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
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
    checked_at TEXT NOT NULL
);
"""


def _make_db(path: Path, user_version: int) -> None:
    with sqlite3.connect(path) as conn:
        if user_version >= 3:
            conn.executescript(_V3_SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {user_version};")


def _user_version(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("PRAGMA user_version;").fetchone()[0]


def test_ensure_v4_auto_migrates_from_v3(tmp_path: Path) -> None:
    """_ensure_v4 on a v3 DB must auto-migrate to v4."""
    from tube_scout.storage.content_db import _ensure_v4

    db = tmp_path / "content_reuse.db"
    _make_db(db, user_version=3)

    _ensure_v4(db)

    assert _user_version(db) == 4


def test_ensure_v4_noop_on_v4(tmp_path: Path) -> None:
    """_ensure_v4 on an already-v4 DB must be a no-op (no error, version unchanged)."""
    from tube_scout.storage.content_db import _ensure_v4, migrate_to_v4

    db = tmp_path / "content_reuse.db"
    _make_db(db, user_version=3)
    migrate_to_v4(db)
    assert _user_version(db) == 4

    _ensure_v4(db)

    assert _user_version(db) == 4


def test_ensure_v4_raises_on_v2(tmp_path: Path) -> None:
    """_ensure_v4 on a v2 DB must raise ValueError containing 'user_version'."""
    from tube_scout.storage.content_db import _ensure_v4

    db = tmp_path / "content_reuse.db"
    _make_db(db, user_version=2)

    with pytest.raises(ValueError, match="user_version"):
        _ensure_v4(db)
