"""T039 RED — fingerprint local-input integration: mp4 and wav_16k inputs.

Verifies that extract_chromaprint_fingerprint accepts both mp4 and wav_16k
input kinds and produces deterministic, equal fingerprints for the same content.
Uses takeout_sample/1-1.강의제목A.mp4 as source; extracts wav_16k via T037 service.
Mocks fpcalc to emit a fixed fingerprint so AudioTooShortError (fixture is 1s)
does not block the test. Real ffmpeg is used for WAV extraction.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURE_MP4 = (
    Path(__file__).parent.parent
    / "fixtures"
    / "takeout_sample"
    / "Takeout"
    / "YouTube 및 YouTube Music"
    / "동영상"
    / "1-1.강의제목A.mp4"
)

_FPCALC_DURATION = 60
_FPCALC_FP = "AQADtFMSRUkiJdmEjzoqJIkSJUqSKEmSJEmSREmSJEmUJEmSJEmSJEmSJEmSJEmS"
_FPCALC_STDOUT = f"DURATION={_FPCALC_DURATION}\nFINGERPRINT={_FPCALC_FP}\n"


def _make_fpcalc_result() -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = _FPCALC_STDOUT
    proc.stderr = ""
    return proc


def test_mp4_input_produces_fingerprint(tmp_path: Path) -> None:
    """extract_chromaprint_fingerprint accepts mp4 path directly via fpcalc."""
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    with patch("subprocess.run", return_value=_make_fpcalc_result()):
        fp_bytes, duration = extract_chromaprint_fingerprint(FIXTURE_MP4)

    assert fp_bytes == _FPCALC_FP.encode("ascii")
    assert duration == float(_FPCALC_DURATION)


def test_wav_16k_input_produces_fingerprint(tmp_path: Path) -> None:
    """extract_chromaprint_fingerprint accepts wav_16k path from extract_wav_16k_mono."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    wav_path = tmp_path / "test.wav"
    extract_wav_16k_mono(FIXTURE_MP4, wav_path)
    assert wav_path.exists(), "WAV must be created by extract_wav_16k_mono"

    with patch("subprocess.run", return_value=_make_fpcalc_result()):
        fp_bytes, duration = extract_chromaprint_fingerprint(wav_path)

    assert fp_bytes == _FPCALC_FP.encode("ascii")
    assert duration == float(_FPCALC_DURATION)


def test_mp4_and_wav_produce_identical_fingerprint(tmp_path: Path) -> None:
    """Both input kinds fed through the same fpcalc mock return equal fingerprints."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    wav_path = tmp_path / "test.wav"
    extract_wav_16k_mono(FIXTURE_MP4, wav_path)

    with patch("subprocess.run", return_value=_make_fpcalc_result()):
        fp_mp4, dur_mp4 = extract_chromaprint_fingerprint(FIXTURE_MP4)

    with patch("subprocess.run", return_value=_make_fpcalc_result()):
        fp_wav, dur_wav = extract_chromaprint_fingerprint(wav_path)

    assert fp_mp4 == fp_wav, (
        f"mp4 and wav_16k must produce same fingerprint bytes. "
        f"mp4={fp_mp4!r} wav={fp_wav!r}"
    )
    assert dur_mp4 == dur_wav


def test_fpcalc_receives_correct_path_for_mp4(tmp_path: Path) -> None:
    """fpcalc subprocess is called with the mp4 file path as last argument."""
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    captured_cmds: list[list[str]] = []

    def spy_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return _make_fpcalc_result()

    with patch("subprocess.run", side_effect=spy_run):
        extract_chromaprint_fingerprint(FIXTURE_MP4)

    assert len(captured_cmds) == 1
    assert str(FIXTURE_MP4) in captured_cmds[0], (
        f"mp4 path must appear in fpcalc command: {captured_cmds[0]}"
    )


def test_fpcalc_receives_correct_path_for_wav(tmp_path: Path) -> None:
    """fpcalc subprocess is called with the wav file path as last argument."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    wav_path = tmp_path / "test.wav"
    extract_wav_16k_mono(FIXTURE_MP4, wav_path)

    captured_cmds: list[list[str]] = []

    def spy_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return _make_fpcalc_result()

    with patch("subprocess.run", side_effect=spy_run):
        extract_chromaprint_fingerprint(wav_path)

    assert len(captured_cmds) == 1
    assert str(wav_path) in captured_cmds[0], (
        f"wav path must appear in fpcalc command: {captured_cmds[0]}"
    )
