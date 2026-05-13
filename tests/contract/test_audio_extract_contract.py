"""Contract tests — audio_extract service signatures (spec 013 T035 RED).

FR-010~FR-012: extract_wav_16k_mono, cleanup_wav, WavLifecycle.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE_DIR = (
    Path(__file__).parent.parent
    / "fixtures"
    / "takeout_sample"
    / "Takeout"
    / "YouTube 및 YouTube Music"
    / "동영상"
)
FIXTURE_MP4 = FIXTURE_DIR / "1-1.강의제목A.mp4"


# ---------------------------------------------------------------------------
# T035-1: extract_wav_16k_mono — creates file with correct specs
# ---------------------------------------------------------------------------

def test_extract_wav_16k_mono_creates_file_with_correct_specs(tmp_path: Path) -> None:
    """extract_wav_16k_mono produces a 16 kHz mono pcm_s16le WAV (verified via ffprobe)."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono

    wav_path = tmp_path / "out.wav"
    result = extract_wav_16k_mono(FIXTURE_MP4, wav_path)

    assert result == wav_path
    assert wav_path.exists(), "wav file must be created"

    probe = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels,codec_name",
            "-of", "csv=p=0",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    parts = probe.stdout.strip().split(",")
    codec, channels, sample_rate = parts[0], parts[1], parts[2]
    assert codec == "pcm_s16le", f"codec must be pcm_s16le, got {codec}"
    assert channels == "1", f"channels must be 1 (mono), got {channels}"
    assert sample_rate == "16000", f"sample_rate must be 16000, got {sample_rate}"


# ---------------------------------------------------------------------------
# T035-2: extract_wav_16k_mono — force=True overwrites existing
# ---------------------------------------------------------------------------

def test_extract_force_overwrite(tmp_path: Path) -> None:
    """force=True must overwrite an existing wav file."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono

    wav_path = tmp_path / "out.wav"
    wav_path.write_bytes(b"old content")
    old_size = wav_path.stat().st_size

    result = extract_wav_16k_mono(FIXTURE_MP4, wav_path, force=True)

    assert result == wav_path
    assert wav_path.stat().st_size != old_size or wav_path.read_bytes() != b"old content", (
        "force=True must overwrite existing wav"
    )


# ---------------------------------------------------------------------------
# T035-3: extract_wav_16k_mono — force=False skips existing
# ---------------------------------------------------------------------------

def test_extract_no_force_skip_existing(tmp_path: Path) -> None:
    """force=False must skip extraction when wav already exists."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono

    wav_path = tmp_path / "out.wav"
    sentinel = b"existing content -- must not change"
    wav_path.write_bytes(sentinel)

    ffmpeg_calls: list = []

    original_run = subprocess.run

    def spy_run(cmd, **kwargs):
        if isinstance(cmd, (list, tuple)) and len(cmd) > 0 and "ffmpeg" in str(cmd[0]):
            ffmpeg_calls.append(cmd)
        return original_run(cmd, **kwargs)

    with patch("subprocess.run", side_effect=spy_run):
        result = extract_wav_16k_mono(FIXTURE_MP4, wav_path, force=False)

    assert result == wav_path
    assert wav_path.read_bytes() == sentinel, "existing wav must not be modified"
    assert len(ffmpeg_calls) == 0, "ffmpeg must not be called when wav exists and force=False"


# ---------------------------------------------------------------------------
# T035-4: extract_wav_16k_mono — raises FileNotFoundError on missing mp4
# ---------------------------------------------------------------------------

def test_extract_raises_on_missing_mp4(tmp_path: Path) -> None:
    """extract_wav_16k_mono raises FileNotFoundError when mp4 does not exist."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono

    missing = tmp_path / "nonexistent.mp4"
    wav_path = tmp_path / "out.wav"

    with pytest.raises(FileNotFoundError):
        extract_wav_16k_mono(missing, wav_path)


# ---------------------------------------------------------------------------
# T035-5: extract_wav_16k_mono — raises RuntimeError on ffmpeg failure
# ---------------------------------------------------------------------------

def test_extract_raises_on_ffmpeg_failure(tmp_path: Path) -> None:
    """extract_wav_16k_mono raises RuntimeError when ffmpeg exits non-zero."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono

    wav_path = tmp_path / "out.wav"

    fail_result = MagicMock(spec=subprocess.CompletedProcess)
    fail_result.returncode = 1
    fail_result.stderr = "ERROR: Invalid data found"

    with patch("subprocess.run", return_value=fail_result):
        with pytest.raises(RuntimeError, match="ffmpeg"):
            extract_wav_16k_mono(FIXTURE_MP4, wav_path)
