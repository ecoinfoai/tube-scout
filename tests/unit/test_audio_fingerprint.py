"""T027 RED — audio_fingerprint.py 9 scenarios (subprocess fpcalc mocked)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Realistic fpcalc stdout for a ~33min audio
_FPCALC_DURATION = 1989
_FPCALC_FP = (
    "AQADtFMSRUkiJdmEjzoqJIkSJUqSKEmSJEmSREmSJEmUJEmSJEmSJEmSJEmSJEmS"
    "JEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmS"
)
_FPCALC_STDOUT = f"DURATION={_FPCALC_DURATION}\nFINGERPRINT={_FPCALC_FP}\n"
_FPCALC_SHORT_STDOUT = "DURATION=25\nFINGERPRINT=AQADtFMSRUkiJdmE\n"


def _make_fpcalc_result(returncode: int = 0, stdout: str = _FPCALC_STDOUT, stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_extract_returns_fingerprint_and_duration(tmp_path: Path) -> None:
    """Scenario 1: fpcalc mock → (fp_bytes, 1989.0), subprocess args verified."""
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    audio = tmp_path / "lecture.mp3"
    audio.write_bytes(b"\x00" * 100)

    captured_cmd: list = []

    def spy_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _make_fpcalc_result()

    with patch("subprocess.run", side_effect=spy_run):
        fp_bytes, duration = extract_chromaprint_fingerprint(audio)

    assert isinstance(fp_bytes, bytes)
    assert len(fp_bytes) >= 16
    assert duration == pytest.approx(1989.0, abs=1.0)
    assert "fpcalc" in captured_cmd
    assert str(audio) in captured_cmd


def test_extract_too_short_raises_audio_too_short_error(tmp_path: Path) -> None:
    """Scenario 2: 25s audio → AudioTooShortError."""
    from tube_scout.services.audio_fingerprint import (
        AudioTooShortError,
        extract_chromaprint_fingerprint,
    )

    audio = tmp_path / "short.mp3"
    audio.write_bytes(b"\x00" * 10)

    with patch("subprocess.run", return_value=_make_fpcalc_result(stdout=_FPCALC_SHORT_STDOUT)):
        with pytest.raises(AudioTooShortError) as exc_info:
            extract_chromaprint_fingerprint(audio)

    assert "25" in str(exc_info.value) or "30" in str(exc_info.value)


def test_extract_fpcalc_nonzero_raises_fingerprint_extract_error(tmp_path: Path) -> None:
    """Scenario 3: fpcalc returncode=1 → FingerprintExtractError with stderr."""
    from tube_scout.services.audio_fingerprint import (
        FingerprintExtractError,
        extract_chromaprint_fingerprint,
    )

    audio = tmp_path / "bad.mp3"
    audio.write_bytes(b"\x00" * 10)
    stderr = "ERROR: fpcalc: cannot open audio file"

    with patch("subprocess.run", return_value=_make_fpcalc_result(returncode=1, stdout="", stderr=stderr)):
        with pytest.raises(FingerprintExtractError) as exc_info:
            extract_chromaprint_fingerprint(audio)

    assert "fpcalc" in str(exc_info.value).lower() or "audio" in str(exc_info.value).lower()


def test_extract_malformed_stdout_raises_fingerprint_extract_error(tmp_path: Path) -> None:
    """Scenario 4: fpcalc stdout missing FINGERPRINT/DURATION → FingerprintExtractError."""
    from tube_scout.services.audio_fingerprint import (
        FingerprintExtractError,
        extract_chromaprint_fingerprint,
    )

    audio = tmp_path / "corrupt.mp3"
    audio.write_bytes(b"\x00" * 10)

    with patch("subprocess.run", return_value=_make_fpcalc_result(stdout="garbage\nno valid lines\n")):
        with pytest.raises(FingerprintExtractError):
            extract_chromaprint_fingerprint(audio)


def test_decode_fingerprint_to_uint32_array() -> None:
    """Scenario 5: decode_fingerprint_to_array returns uint32 ndarray.

    Uses real chromaprint b64 from spike fixture (33-min lecture audio) — the
    placeholder _FPCALC_FP is intentionally synthetic (not valid chromaprint
    base64) for stdout-parsing tests, so we load the real one here.
    """
    numpy = pytest.importorskip("numpy")
    pytest.importorskip("chromaprint")

    import re

    from tube_scout.services.audio_fingerprint import decode_fingerprint_to_array

    fixture_path = Path(__file__).parent.parent / "fixtures" / "spec012" / "spike_fp_v1.txt"
    fp_text = fixture_path.read_text()
    match = re.search(r"^FINGERPRINT=(\S+)$", fp_text, re.MULTILINE)
    assert match is not None, f"Spike fixture missing FINGERPRINT line: {fixture_path}"
    fp_b64 = match.group(1).encode("ascii")

    arr = decode_fingerprint_to_array(fp_b64)

    assert arr.dtype == numpy.uint32
    assert arr.ndim == 1
    assert len(arr) > 0


def test_hamming_distance_self_is_zero() -> None:
    """Scenario 6: hamming_distance_per_int(arr, arr) == 0.0."""
    numpy = pytest.importorskip("numpy")

    from tube_scout.services.audio_fingerprint import hamming_distance_per_int

    arr = numpy.array([0xDEADBEEF, 0xCAFEBABE, 0x12345678], dtype=numpy.uint32)
    result = hamming_distance_per_int(arr, arr)
    assert result == pytest.approx(0.0, abs=1e-9)


def test_hamming_distance_shifted_array() -> None:
    """Scenario 7: rolled array → ~14-16 bits hamming distance."""
    numpy = pytest.importorskip("numpy")

    from tube_scout.services.audio_fingerprint import hamming_distance_per_int

    rng = numpy.random.default_rng(42)
    arr = rng.integers(0, 2**32, size=1000, dtype=numpy.uint32)
    shifted = numpy.roll(arr, 100)
    result = hamming_distance_per_int(arr, shifted)
    assert 10.0 <= result <= 22.0, f"Expected ~14-16 bits, got {result}"


def test_best_alignment_same_array_returns_zero() -> None:
    """Scenario 8: best_alignment_hamming(arr, arr) → (0.0, 0)."""
    numpy = pytest.importorskip("numpy")

    from tube_scout.services.audio_fingerprint import best_alignment_hamming

    rng = numpy.random.default_rng(99)
    arr = rng.integers(0, 2**32, size=500, dtype=numpy.uint32)
    min_dist, best_offset = best_alignment_hamming(arr, arr, window_frames=50, step=1)

    assert min_dist == pytest.approx(0.0, abs=1e-9)
    assert best_offset == 0


def test_best_alignment_detects_known_offset() -> None:
    """Scenario 9: array B shifted +50 frames → best_offset near 50."""
    numpy = pytest.importorskip("numpy")

    from tube_scout.services.audio_fingerprint import best_alignment_hamming

    rng = numpy.random.default_rng(7)
    arr = rng.integers(0, 2**32, size=600, dtype=numpy.uint32)
    b = numpy.concatenate([numpy.zeros(50, dtype=numpy.uint32), arr[:-50]])
    min_dist, best_offset = best_alignment_hamming(arr, b, window_frames=100, step=1)

    assert min_dist < 5.0, f"Expected low hamming at best alignment, got {min_dist}"
