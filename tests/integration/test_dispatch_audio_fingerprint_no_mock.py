"""AT-NEW-6 regression test — dispatch_audio_fingerprint without mocking dispatch.

Original integration tests (test_dispatch_audio_fingerprint.py) mocked
fetch_audio_via_ytdlp + extract_chromaprint_fingerprint at module-level
but the dispatch loop body itself was never exercised under the new
G-4 fix (current_video_id_ref = []). adversary T047d caught the
IndexError when slice assignment was missing — this test guards.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_dispatch_audio_fingerprint_with_empty_video_id_ref(tmp_path: Path) -> None:
    """AT-NEW-6 guard: empty current_video_id_ref must not IndexError.

    G-4 introduced empty-list initialization (`current_video_id_ref = []`);
    the dispatch loop must use slice assignment to write the in-progress
    video_id, not subscript [0] which raises IndexError on empty list.
    """
    from tube_scout.cli.collect import dispatch_audio_fingerprint

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "fp.db"
    # initialize empty SQLite + v3 schema
    from tube_scout.storage.content_db import migrate_to_v3
    migrate_to_v3(db_path)

    audit_writer = MagicMock()
    current_video_id_ref: list[str] = []  # G-4: empty list init

    fake_audio = tmp_path / "fake.mp3"
    fake_audio.write_bytes(b"\x00" * 100)

    with patch(
        "tube_scout.services.ytdlp_adapter.fetch_audio_via_ytdlp",
        return_value=fake_audio,
    ), patch(
        "tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint",
        return_value=(b"AQAfake__fingerprint__b64____", 60.0),
    ):
        # Real dispatch — must not raise IndexError
        dispatch_audio_fingerprint(
            video_ids=["abcdefghijk"],
            audio_temp=audio_temp,
            db_path=db_path,
            audit_writer=audit_writer,
            current_video_id_ref=current_video_id_ref,
        )

    # AT-NEW-6 invariant: slice assignment populated the ref
    assert current_video_id_ref == ["abcdefghijk"]


def test_dispatch_audio_fingerprint_handles_multiple_videos(tmp_path: Path) -> None:
    """Slice assignment must overwrite (not append) per video iteration."""
    from tube_scout.cli.collect import dispatch_audio_fingerprint

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "fp.db"
    from tube_scout.storage.content_db import migrate_to_v3
    migrate_to_v3(db_path)

    current_video_id_ref: list[str] = []

    fake_audio = tmp_path / "fake.mp3"
    fake_audio.write_bytes(b"\x00" * 100)

    with patch(
        "tube_scout.services.ytdlp_adapter.fetch_audio_via_ytdlp",
        return_value=fake_audio,
    ), patch(
        "tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint",
        return_value=(b"AQAfake__fingerprint__b64____", 60.0),
    ):
        dispatch_audio_fingerprint(
            video_ids=["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"],
            audio_temp=audio_temp,
            db_path=db_path,
            audit_writer=MagicMock(),
            current_video_id_ref=current_video_id_ref,
        )

    # After loop: ref holds the LAST processed video_id
    assert current_video_id_ref == ["ccccccccccc"]
    assert len(current_video_id_ref) == 1  # never grew via append
