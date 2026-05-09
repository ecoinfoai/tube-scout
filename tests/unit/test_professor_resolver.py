"""Unit tests for professor_resolver service (T015 RED).

Tests verify professor pool registration, idempotency, collision detection,
membership removal, caption pool resolution, and boundary B-6 (no direct
channels.json parsing).
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.services.professor_resolver import (
    list_professors,
    map_professor,
    resolve_caption_pool,
    unmap_professor,
)


def _db(tmp_path: Path) -> Path:
    return build_clean_v2_db(tmp_path / "pr.db")


def test_map_new_professor(tmp_path: Path) -> None:
    """map_professor inserts into professor_pool and professor_pool_membership."""
    db = _db(tmp_path)
    mapping = map_professor(
        professor_id="prof-x",
        display_name="Test Professor",
        channel_alias="ch-test",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )
    assert mapping.professor_id == "prof-x"
    assert mapping.channel_alias == "ch-test"

    conn = sqlite3.connect(str(db))
    pp = conn.execute("SELECT professor_id FROM professor_pool WHERE professor_id='prof-x'").fetchone()
    pm = conn.execute(
        "SELECT professor_id FROM professor_pool_membership WHERE professor_id='prof-x'"
    ).fetchone()
    conn.close()
    assert pp is not None
    assert pm is not None


def test_map_idempotent(tmp_path: Path) -> None:
    """Calling map_professor twice with same args raises no error and adds no duplicate rows."""
    db = _db(tmp_path)
    kwargs = dict(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-a",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )
    map_professor(**kwargs)
    map_professor(**kwargs)  # idempotent — no error

    conn = sqlite3.connect(str(db))
    count = conn.execute(
        "SELECT COUNT(*) FROM professor_pool_membership WHERE professor_id='prof-x'"
    ).fetchone()[0]
    conn.close()
    assert count == 1


def test_map_channel_owner_collision(tmp_path: Path) -> None:
    """Registering __channel_owner__ for the same alias to a different professor raises ValueError."""
    db = _db(tmp_path)
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-shared",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )
    with pytest.raises(ValueError) as exc_info:
        map_professor(
            professor_id="prof-y",
            display_name="Prof Y",
            channel_alias="ch-shared",
            author_marker="__channel_owner__",
            db_path=db,
            registered_by="admin",
        )
    msg = str(exc_info.value)
    assert "ch-shared" in msg
    assert "prof-x" in msg
    assert "one channel" in msg.lower() or "__channel_owner__" in msg


def test_unmap_existing(tmp_path: Path) -> None:
    """unmap_professor returns True and removes the membership row."""
    db = _db(tmp_path)
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-a",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )
    result = unmap_professor("prof-x", "ch-a", "__channel_owner__", db)
    assert result is True

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT 1 FROM professor_pool_membership WHERE professor_id='prof-x'"
    ).fetchone()
    conn.close()
    assert row is None


def test_unmap_missing(tmp_path: Path) -> None:
    """unmap_professor returns False when the mapping row does not exist."""
    db = _db(tmp_path)
    result = unmap_professor("prof-nonexistent", "ch-x", "__channel_owner__", db)
    assert result is False


def test_resolve_caption_pool_multi_channel(tmp_path: Path) -> None:
    """resolve_caption_pool returns all video refs across multiple channels."""
    db = _db(tmp_path)
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-a",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-b",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )

    # Populate processing_status with videos for both channels
    conn = sqlite3.connect(str(db))
    conn.executemany(
        "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
        [("vid-a1", "ch-a", "fingerprinted", "2026-01-01"),
         ("vid-a2", "ch-a", "fingerprinted", "2026-01-01"),
         ("vid-b1", "ch-b", "fingerprinted", "2026-01-01")],
    )
    conn.commit()
    conn.close()

    pool = resolve_caption_pool("prof-x", db)
    assert pool.professor_id == "prof-x"
    video_ids = {vr.video_id for vr in pool.video_refs}
    assert "vid-a1" in video_ids
    assert "vid-a2" in video_ids
    assert "vid-b1" in video_ids


def test_resolve_caption_pool_no_mapping_raises(tmp_path: Path) -> None:
    """resolve_caption_pool raises ValueError for an unregistered professor_id."""
    db = _db(tmp_path)
    with pytest.raises(ValueError) as exc_info:
        resolve_caption_pool("prof-unknown", db)
    msg = str(exc_info.value)
    assert "prof-unknown" in msg
    assert "tube-scout content professor map" in msg


def test_resolve_uses_channel_alias_helper(tmp_path: Path) -> None:
    """resolve_caption_pool must not directly parse channels.json (boundary B-6).

    The function should query the DB for channel_alias values from
    professor_pool_membership — direct file reads of channels.json are forbidden.
    We verify that no code path in professor_resolver opens a file named
    'channels.json' by patching Path.open and checking it was never called
    with a path containing 'channels'.
    """
    db = _db(tmp_path)
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-test",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="admin",
    )

    opened_paths: list[str] = []
    original_open = Path.open

    def tracking_open(self: Path, *args, **kwargs):  # type: ignore[override]
        opened_paths.append(str(self))
        return original_open(self, *args, **kwargs)

    with patch.object(Path, "open", tracking_open):
        try:
            resolve_caption_pool("prof-x", db)
        except Exception:
            pass  # pool may be empty; we only care about file access

    channels_json_reads = [p for p in opened_paths if "channels" in p and p.endswith(".json")]
    assert channels_json_reads == [], (
        f"professor_resolver directly read channels.json (boundary B-6 violation): "
        f"{channels_json_reads}"
    )
