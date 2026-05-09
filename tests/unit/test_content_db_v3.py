"""Unit tests for content_db v3 migration (spec 012, FR-012, FR-013, data-model E-3).

T012 RED — 5 scenarios for migrate_to_v3 + 3 audio_fingerprint helpers.
"""

import sqlite3
from pathlib import Path

import pytest


def _create_v2_db(db_path: Path) -> None:
    """Bootstrap a minimal v2-compatible DB (spec 011 schema baseline)."""
    from tube_scout.storage.content_db import ContentDB, migrate_to_v2

    db = ContentDB(db_path)
    db.close()
    migrate_to_v2(db_path)


def test_migrate_to_v3_creates_audio_fingerprint_table(tmp_path):
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _create_v2_db(db_path)
    migrate_to_v3(db_path)

    conn = sqlite3.connect(str(db_path))
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "audio_fingerprint" in tables


def test_migrate_to_v3_sets_user_version_3(tmp_path):
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _create_v2_db(db_path)
    migrate_to_v3(db_path)

    conn = sqlite3.connect(str(db_path))
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version == 3


def test_migrate_to_v3_is_idempotent(tmp_path):
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    _create_v2_db(db_path)
    migrate_to_v3(db_path)
    migrate_to_v3(db_path)  # second call must not raise

    conn = sqlite3.connect(str(db_path))
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version == 3


def test_insert_and_get_audio_fingerprint(tmp_path):
    from tube_scout.storage.content_db import (
        get_audio_fingerprint,
        insert_audio_fingerprint,
        migrate_to_v3,
    )

    db_path = tmp_path / "content_reuse.db"
    _create_v2_db(db_path)
    migrate_to_v3(db_path)

    fp_bytes = b"AQA-rVMSRUkiJdmEjzoq"
    insert_audio_fingerprint(
        db_path,
        video_id="abc12345678",
        fingerprint=fp_bytes,
        duration=1823.4,
        extracted_at="2026-05-09T12:00:00+09:00",
    )

    result = get_audio_fingerprint(db_path, "abc12345678")
    assert result is not None
    fp, duration, extracted_at, source = result
    assert fp == fp_bytes
    assert abs(duration - 1823.4) < 0.01
    assert source == "fpcalc:1.6.0"


def test_audio_fingerprint_exists(tmp_path):
    from tube_scout.storage.content_db import (
        audio_fingerprint_exists,
        insert_audio_fingerprint,
        migrate_to_v3,
    )

    db_path = tmp_path / "content_reuse.db"
    _create_v2_db(db_path)
    migrate_to_v3(db_path)

    assert not audio_fingerprint_exists(db_path, "abc12345678")
    insert_audio_fingerprint(
        db_path,
        video_id="abc12345678",
        fingerprint=b"AQA-rVMSRUkiJdmEjzoq",
        duration=100.0,
        extracted_at="2026-05-09T12:00:00+09:00",
    )
    assert audio_fingerprint_exists(db_path, "abc12345678")
