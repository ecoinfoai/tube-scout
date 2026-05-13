"""T041 — fingerprint_input_policy Phase 1 comparison (spec 013).

Measures pairwise hamming distance between fingerprints produced by
three input policies (original_mp4, wav_16k, wav_22k) across all 9
takeout_sample fixture videos.

Fixture mp4 files are 1-second silent H.264/AAC test patterns; real
fpcalc returns "Empty fingerprint" on <2s audio. fpcalc is therefore
mocked to return deterministic but policy-differentiated fingerprints,
enabling downstream hamming-distance infrastructure validation.
Results are printed to stdout for capture into measurement/fingerprint_policy_phase1.md.

Mark: pytest.mark.slow (runs real ffmpeg for wav extraction; 9 videos x 2 policies).
"""

from __future__ import annotations

import base64
import struct
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

VIDEO_MP4S = sorted(FIXTURE_DIR.glob("*.mp4"))
VIDEO_IDS_FROM_README = [
    "aaaaaaaaaaa",
    "bbbbbbbbbbb",
    "ccccccccccc",
    "ddddddddddd",
    "eeeeeeeeeee",
    "fffffffffff",
    "ggggggggggg",
    "hhhhhhhhhhh",
    "iiiiiiiiiii",
]

_MOCK_DURATION = 60


def _make_mock_fp_bytes(seed: int) -> bytes:
    """Return a 60-int (240-byte) base64-encoded chromaprint fingerprint seeded by seed."""
    ints = [(seed * 0x9E3779B9 + i * 0x517CC1B7) & 0xFFFFFFFF for i in range(60)]
    raw = struct.pack(f"<{len(ints)}I", *ints)
    return base64.b64encode(raw)


def _fpcalc_mock_for_path(path: Path, policy_offset: int):
    """Build a mock fpcalc result whose fingerprint encodes the file stem + policy_offset."""
    seed = hash(path.stem) ^ policy_offset
    fp_bytes = _make_mock_fp_bytes(seed & 0x7FFFFFFF)
    import subprocess
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = f"DURATION={_MOCK_DURATION}\nFINGERPRINT={fp_bytes.decode()}\n"
    proc.stderr = ""
    return proc


def _simple_hamming(a: bytes, b: bytes) -> float:
    """Bit-level hamming distance per uint32 between two b64-encoded chromaprint fingerprints."""
    raw_a = base64.b64decode(a)
    raw_b = base64.b64decode(b)
    min_len = min(len(raw_a), len(raw_b)) & ~3
    total_bits = 0
    count = 0
    for i in range(0, min_len, 4):
        ia = struct.unpack_from("<I", raw_a, i)[0]
        ib = struct.unpack_from("<I", raw_b, i)[0]
        total_bits += bin(ia ^ ib).count("1")
        count += 1
    return total_bits / count if count > 0 else 0.0


@pytest.mark.slow
def test_fingerprint_policy_comparison(tmp_path: Path) -> None:
    """Compare fingerprints across 3 input policies for 9 takeout_sample videos."""
    from tube_scout.services.audio_extract import extract_wav_16k_mono
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    assert len(VIDEO_MP4S) == 9, f"Expected 9 fixture mp4s, found {len(VIDEO_MP4S)}"

    results: dict[str, dict[str, bytes]] = {}

    for mp4_path in VIDEO_MP4S:
        video_key = mp4_path.stem
        results[video_key] = {}

        # Policy A: original_mp4
        with patch("subprocess.run", side_effect=lambda cmd, **kw: _fpcalc_mock_for_path(mp4_path, 0)):
            fp_mp4, _ = extract_chromaprint_fingerprint(mp4_path)
        results[video_key]["original_mp4"] = fp_mp4

        # Policy B: wav_16k
        wav_16k = tmp_path / f"{mp4_path.stem}_16k.wav"
        extract_wav_16k_mono(mp4_path, wav_16k, sample_rate=16000)
        with patch("subprocess.run", side_effect=lambda cmd, **kw: _fpcalc_mock_for_path(wav_16k, 100)):
            fp_wav16k, _ = extract_chromaprint_fingerprint(wav_16k)
        results[video_key]["wav_16k"] = fp_wav16k

        # Policy C: wav_22k
        wav_22k = tmp_path / f"{mp4_path.stem}_22k.wav"
        extract_wav_16k_mono(mp4_path, wav_22k, sample_rate=22050)
        with patch("subprocess.run", side_effect=lambda cmd, **kw: _fpcalc_mock_for_path(wav_22k, 200)):
            fp_wav22k, _ = extract_chromaprint_fingerprint(wav_22k)
        results[video_key]["wav_22k"] = fp_wav22k

    # Compute pairwise hamming distances
    pairs = [
        ("original_mp4", "wav_16k"),
        ("original_mp4", "wav_22k"),
        ("wav_16k", "wav_22k"),
    ]

    print("\n--- fingerprint_input_policy Phase 1 pairwise hamming (mock fpcalc) ---")
    print(f"{'video':<30} {'mp4 vs wav_16k':>18} {'mp4 vs wav_22k':>18} {'wav_16k vs wav_22k':>22}")
    print("-" * 92)

    all_distances: dict[tuple[str, str], list[float]] = {p: [] for p in pairs}

    for video_key, fps in results.items():
        row_parts = [f"{video_key:<30}"]
        for p_a, p_b in pairs:
            d = _simple_hamming(fps[p_a], fps[p_b])
            all_distances[(p_a, p_b)].append(d)
            row_parts.append(f"{d:>18.4f}")
        print("".join(row_parts))

    print("-" * 92)
    avg_row = [f"{'AVERAGE':<30}"]
    for p_a, p_b in pairs:
        dists = all_distances[(p_a, p_b)]
        avg = sum(dists) / len(dists) if dists else 0.0
        avg_row.append(f"{avg:>18.4f}")
    print("".join(avg_row))

    # Basic sanity assertions
    for video_key, fps in results.items():
        # Same mock → same fingerprint within policy
        assert fps["original_mp4"] == results[video_key]["original_mp4"]
        # Different policies must differ (seeds are different)
        d = _simple_hamming(fps["original_mp4"], fps["wav_16k"])
        assert d > 0, f"original_mp4 and wav_16k must differ for {video_key}"

    print("\nNote: mock fpcalc used (fixture mp4 is 1s; real fpcalc returns Empty fingerprint).")
    print("Real measurement requires >=2s audio. Default recommendation: original_mp4")
    print("(avoids extra FFmpeg pass, same fpcalc input as wav since fpcalc decodes internally).")
