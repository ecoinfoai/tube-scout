"""Unit tests — WavLifecycle context manager (spec 013 T036 RED).

FR-010: WavLifecycle cleanup behavior on normal exit, KeyboardInterrupt, and keep=True.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# T036-1: WavLifecycle deletes wav on normal exit
# ---------------------------------------------------------------------------

def test_wav_lifecycle_deletes_on_normal_exit(tmp_path: Path) -> None:
    """WAV file must be deleted after successful context block exit."""
    from tube_scout.services.audio_extract import WavLifecycle

    mp4_path = tmp_path / "video.mp4"
    mp4_path.write_bytes(b"fake mp4")
    wav_dir = tmp_path / "wav"
    wav_dir.mkdir()
    video_id = "TESTVID0001"

    with WavLifecycle(mp4_path, wav_dir, video_id, keep=False) as wav_path:
        assert wav_path.parent == wav_dir
        assert wav_path.name == f"{video_id}.wav"
        wav_path.write_bytes(b"fake wav data")
        assert wav_path.exists(), "wav must exist inside context block"

    assert not wav_path.exists(), "wav must be deleted after normal context exit"


# ---------------------------------------------------------------------------
# T036-2: WavLifecycle deletes wav on KeyboardInterrupt (SIGINT simulation)
# ---------------------------------------------------------------------------

def test_wav_lifecycle_deletes_on_sigint(tmp_path: Path) -> None:
    """WAV file must be deleted even when KeyboardInterrupt is raised inside context."""
    from tube_scout.services.audio_extract import WavLifecycle

    mp4_path = tmp_path / "video.mp4"
    mp4_path.write_bytes(b"fake mp4")
    wav_dir = tmp_path / "wav"
    wav_dir.mkdir()
    video_id = "TESTVID0002"

    wav_path_ref: list[Path] = []

    with pytest.raises(KeyboardInterrupt):
        with WavLifecycle(mp4_path, wav_dir, video_id, keep=False) as wav_path:
            wav_path_ref.append(wav_path)
            wav_path.write_bytes(b"fake wav data")
            raise KeyboardInterrupt("SIGINT simulation")

    assert len(wav_path_ref) == 1
    assert not wav_path_ref[0].exists(), (
        "wav must be deleted even when KeyboardInterrupt propagates"
    )


# ---------------------------------------------------------------------------
# T036-3: WavLifecycle preserves wav when keep=True
# ---------------------------------------------------------------------------

def test_wav_lifecycle_preserves_when_keep_true(tmp_path: Path) -> None:
    """WAV file must NOT be deleted when keep=True."""
    from tube_scout.services.audio_extract import WavLifecycle

    mp4_path = tmp_path / "video.mp4"
    mp4_path.write_bytes(b"fake mp4")
    wav_dir = tmp_path / "wav"
    wav_dir.mkdir()
    video_id = "TESTVID0003"

    with WavLifecycle(mp4_path, wav_dir, video_id, keep=True) as wav_path:
        wav_path.write_bytes(b"fake wav data")

    assert wav_path.exists(), "wav must be preserved when keep=True"
