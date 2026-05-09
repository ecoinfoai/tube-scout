"""Audio fingerprint module — chromaprint subprocess + decode + similarity.

No yt-dlp, no DB (those are in adjacent modules per B-X1-2).
B-X1-9: separate from services/fingerprint.py (text SHA — spec 011).
"""
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from tube_scout.services.ytdlp_errors import AudioTooShortError, FingerprintExtractError

if TYPE_CHECKING:
    import numpy as np

_MIN_DURATION_SECONDS = 30
_DURATION_RE = re.compile(r"^DURATION=(\d+)$", re.MULTILINE)
_FINGERPRINT_RE = re.compile(r"^FINGERPRINT=(\S+)$", re.MULTILINE)


def _parse_fpcalc_stdout(stdout: str) -> tuple[bytes, float]:
    """Extract DURATION + FINGERPRINT lines from fpcalc stdout.

    Args:
        stdout: fpcalc process stdout string.

    Returns:
        (fingerprint_b64_bytes, duration_float).

    Raises:
        FingerprintExtractError: Missing DURATION or FINGERPRINT lines.
    """
    dur_match = _DURATION_RE.search(stdout)
    fp_match = _FINGERPRINT_RE.search(stdout)

    if not dur_match or not fp_match:
        raise FingerprintExtractError(
            "fpcalc stdout missing DURATION or FINGERPRINT lines. "
            "Verify ffmpeg available and audio file not corrupt."
        )

    duration = float(dur_match.group(1))
    fp_b64 = fp_match.group(1).encode("ascii")
    return fp_b64, duration


def _verify_fingerprint_sanity(fp_b64: bytes) -> None:
    """Validate b64 length >= 16 bytes (RV-4).

    Args:
        fp_b64: ASCII base64 fingerprint bytes.

    Raises:
        FingerprintExtractError: Fingerprint is suspiciously short.
    """
    if len(fp_b64) < 16:
        raise FingerprintExtractError(
            f"Fingerprint length {len(fp_b64)} < 16 bytes; audio may be corrupt."
        )


def extract_chromaprint_fingerprint(
    audio_path: Path,
    length_seconds: int = 0,
    timeout_seconds: float = 60.0,
) -> tuple[bytes, float]:
    """Run fpcalc subprocess, return (fp_b64_bytes, duration_seconds).

    Args:
        audio_path: Path to audio file (mp3/wav/etc., fpcalc handles decode).
        length_seconds: 0 for full length, >0 for first N seconds only.
        timeout_seconds: subprocess timeout. fpcalc is fast (<1s for 33min mp3).

    Returns:
        (fingerprint_b64_ascii_bytes, duration_seconds).

    Raises:
        FingerprintExtractError: audio file missing, fpcalc returncode != 0,
            or stdout missing FINGERPRINT/DURATION lines.
        AudioTooShortError: duration < 30 seconds.
        subprocess.TimeoutExpired: fpcalc hung.
    """
    cmd = ["fpcalc", "-length", str(length_seconds), str(audio_path)]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if result.returncode != 0:
        last_err = (result.stderr.strip().splitlines() or ["unknown error"])[-1]
        raise FingerprintExtractError(
            f"fpcalc failed for {audio_path}: {last_err}. "
            "Verify ffmpeg available and audio file not corrupt."
        )

    fp_b64, duration = _parse_fpcalc_stdout(result.stdout)
    _verify_fingerprint_sanity(fp_b64)

    if duration < _MIN_DURATION_SECONDS:
        raise AudioTooShortError(
            f"Audio {audio_path} is {duration:.0f}s; "
            "minimum 30s required for fingerprint."
        )

    return fp_b64, duration


def decode_fingerprint_to_array(fp_b64: bytes) -> "np.ndarray":
    """Decode chromaprint base64 to uint32 numpy array.

    Lazy-imports chromaprint (from pyacoustid PyPI) and numpy.

    Args:
        fp_b64: ASCII bytes from extract_chromaprint_fingerprint().

    Returns:
        Shape (n_frames,), dtype uint32.

    Raises:
        ImportError: chromaprint or numpy not available.
        FingerprintExtractError: decode produced empty array.
    """
    try:
        import chromaprint
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "chromaprint/numpy not available. Install via `nix develop` "
            "and ensure libchromaprint.so is in LD_LIBRARY_PATH."
        ) from exc

    raw_ints, _version = chromaprint.decode_fingerprint(fp_b64)
    if not raw_ints:
        raise FingerprintExtractError(
            "chromaprint decode produced empty array; b64 may be corrupt."
        )

    return np.array(raw_ints, dtype=np.uint32)


def hamming_distance_per_int(a: "np.ndarray", b: "np.ndarray") -> float:
    """Bit-level hamming distance averaged per uint32.

    Args:
        a, b: uint32 arrays of equal length.

    Returns:
        Mean bits-flipped per uint32 (range 0.0..32.0).

    Raises:
        ValueError: arrays have unequal length or non-uint32 dtype.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "numpy not available. "
            "Install via `uv sync --extra ml-sentiment` or `nix develop`."
        ) from exc

    if a.shape != b.shape:
        raise ValueError(
            f"Arrays must have equal shape; got {a.shape} vs {b.shape}."
        )
    if a.dtype != np.uint32 or b.dtype != np.uint32:
        raise ValueError(
            f"Arrays must be dtype uint32; got {a.dtype} and {b.dtype}."
        )

    xor = np.bitwise_xor(a, b)
    bits = np.unpackbits(xor.view(np.uint8)).reshape(-1, 32).sum(axis=1)
    return float(bits.mean())


def best_alignment_hamming(
    a: "np.ndarray",
    b: "np.ndarray",
    window_frames: int = 400,
    step: int = 4,
) -> tuple[float, int]:
    """Search ±window_frames for min hamming distance.

    Args:
        a, b: uint32 fingerprint arrays (different lengths OK).
        window_frames: ±N frames offset search range.
        step: offset increment.

    Returns:
        (min_hamming_per_int, best_offset_frames).
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "numpy not available. "
            "Install via `uv sync --extra ml-sentiment` or `nix develop`."
        ) from exc

    n = min(len(a), len(b))
    best_dist = float("inf")
    best_offset = 0

    for offset in range(-window_frames, window_frames + 1, step):
        if offset >= 0:
            a_slice = a[offset: offset + n]
            b_slice = b[:n - offset] if offset < n else b[:0]
        else:
            a_slice = a[:n + offset]
            b_slice = b[-offset: n]

        compare_len = min(len(a_slice), len(b_slice))
        if compare_len < 16:
            continue

        dist = hamming_distance_per_int(
            a_slice[:compare_len].astype(np.uint32),
            b_slice[:compare_len].astype(np.uint32),
        )
        if dist < best_dist:
            best_dist = dist
            best_offset = offset

    return best_dist, best_offset
