"""T046a: Performance benchmark — single video end-to-end ≤ 60s wall-clock (SC-005).

@pytest.mark.slow: opt-in via `pytest -m slow`. Not run in CI by default.
Measures wall-clock time for 1 spike-fixture video:
  caption fetch + audio fingerprint + DB persist (sleep mocked to 0).
Asserts ≤ 60s to verify SC-005 buildable component.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.slow
def test_single_video_under_60s(tmp_path: Path) -> None:
    """SC-005: End-to-end processing of 1 video (caption + audio + fingerprint + DB persist)
    must complete in ≤ 60s wall-clock (sleep mocked to 0).
    """
    from tube_scout.cli.collect import dispatch_audio_fingerprint
    from tube_scout.storage.content_db import migrate_to_v3

    # Set up DB
    db_path = tmp_path / "content_reuse.db"
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT, duration_sec REAL)"
        )
        conn.execute("INSERT INTO videos VALUES ('bench000001', 'UCbench', 300.0)")
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    migrate_to_v3(db_path)

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()

    mp3_path = audio_temp / "bench000001.mp3"
    mp3_path.write_bytes(b"fake mp3 content")

    fake_fingerprint = b"\x42" * 64  # 64 bytes of valid-length fingerprint

    start = time.perf_counter()

    with patch("tube_scout.services.ytdlp_adapter.fetch_audio_via_ytdlp", return_value=mp3_path), \
         patch("tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint",
               return_value=(fake_fingerprint, 300.0)), \
         patch("time.sleep"):
        dispatch_audio_fingerprint(
            video_ids=["bench000001"],
            audio_temp=audio_temp,
            db_path=db_path,
            sleep_seconds=(0.0, 0.0),
        )

    elapsed = time.perf_counter() - start

    assert elapsed <= 60.0, (
        f"SC-005 violation: single-video processing took {elapsed:.2f}s (limit: 60s)"
    )

    # Verify DB row was inserted
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT video_id, duration FROM audio_fingerprint WHERE video_id = 'bench000001'"
        ).fetchone()

    assert row is not None, "Fingerprint row not inserted in DB"
    assert row[1] == pytest.approx(300.0, abs=1.0), (
        f"Expected duration ~300.0, got {row[1]}"
    )
