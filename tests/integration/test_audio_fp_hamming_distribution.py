"""T070 — audio_fp_hamming threshold measurement (spec 013 Phase 3).

Measures Chromaprint Hamming distance distribution across all 36 pairs
of the 9-video PoC fixture to determine the optimal threshold for
RE_RECORDED_SAME_CONTENT detection in pattern_classifier.

Requires: fpcalc installed (chromaprint package in devShell).
Skips if mp4 files are not found or fpcalc is unavailable.
"""

from __future__ import annotations

import subprocess
import sys
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.slow

FIXTURE_VIDEOS = Path(__file__).parent.parent / "fixtures" / "takeout_sample" / "Takeout" / \
    "YouTube 및 YouTube Music" / "동영상"


class FpResult(NamedTuple):
    video_id: str
    fingerprint: bytes
    duration: float


def _run_fpcalc(mp4_path: Path) -> FpResult | None:
    """Run fpcalc on a single mp4 and return fingerprint bytes + duration."""
    try:
        result = subprocess.run(
            ["fpcalc", "-raw", str(mp4_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    duration = 0.0
    fp_ints: list[int] = []
    for line in result.stdout.splitlines():
        if line.startswith("DURATION="):
            try:
                duration = float(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("FINGERPRINT="):
            raw = line.split("=", 1)[1].strip()
            try:
                fp_ints = [int(x) for x in raw.split(",") if x]
            except ValueError:
                return None

    if not fp_ints:
        return None

    import struct
    fp_bytes = struct.pack(f"<{len(fp_ints)}I", *fp_ints)
    video_id = mp4_path.stem.split(".")[0] if "." in mp4_path.stem else mp4_path.stem
    return FpResult(video_id=video_id, fingerprint=fp_bytes, duration=duration)


def _hamming_distance(a: bytes, b: bytes) -> int:
    """Compute Hamming distance between two equal-length byte arrays."""
    min_len = min(len(a), len(b))
    distance = 0
    for byte_a, byte_b in zip(a[:min_len], b[:min_len]):
        xor = byte_a ^ byte_b
        distance += bin(xor).count("1")
    # Count remaining bytes as all-different
    distance += (max(len(a), len(b)) - min_len) * 8
    return distance


@pytest.fixture(scope="module")
def mp4_files() -> list[Path]:
    mp4s = list(FIXTURE_VIDEOS.glob("*.mp4"))
    if not mp4s:
        pytest.skip(f"No mp4 files found in {FIXTURE_VIDEOS}")
    return mp4s


@pytest.fixture(scope="module")
def fingerprints(mp4_files: list[Path]) -> list[FpResult]:
    results = []
    for mp4 in mp4_files:
        fp = _run_fpcalc(mp4)
        if fp is None:
            pytest.skip("fpcalc not available or failed — install chromaprint package")
        results.append(fp)
    return results


def test_hamming_distribution_all_pairs(fingerprints: list[FpResult]) -> None:
    """Measure and print Hamming distance for all C(N,2) pairs.

    This test prints the distribution to stdout so the developer can
    determine the appropriate audio_fp_hamming_threshold.
    Always passes — it is a measurement test, not an assertion test.
    """
    pairs = list(combinations(fingerprints, 2))
    distances = []
    for fp_a, fp_b in pairs:
        d = _hamming_distance(fp_a.fingerprint, fp_b.fingerprint)
        distances.append((fp_a.video_id, fp_b.video_id, d))

    distances.sort(key=lambda x: x[2])

    print(f"\n=== audio_fp_hamming distribution ({len(distances)} pairs) ===")
    print(f"{'Source':<15} {'Target':<15} {'Hamming':>8}")
    print("-" * 40)
    for src, tgt, d in distances:
        print(f"{src:<15} {tgt:<15} {d:>8}")

    if distances:
        hamming_vals = [d for _, _, d in distances]
        print(f"\nMin:    {min(hamming_vals)}")
        print(f"Max:    {max(hamming_vals)}")
        print(f"Median: {sorted(hamming_vals)[len(hamming_vals)//2]}")
        print(f"Mean:   {sum(hamming_vals)/len(hamming_vals):.1f}")

    # Always passes — measurement only
    assert len(distances) > 0


def test_same_video_hamming_is_zero(fingerprints: list[FpResult]) -> None:
    """A fingerprint compared with itself must have Hamming distance 0."""
    for fp in fingerprints:
        d = _hamming_distance(fp.fingerprint, fp.fingerprint)
        assert d == 0, f"Self-Hamming for {fp.video_id} must be 0, got {d}"


def test_fpcalc_returns_fingerprints(mp4_files: list[Path]) -> None:
    """fpcalc produces valid fingerprints for all 9 PoC mp4 files."""
    for mp4 in mp4_files:
        fp = _run_fpcalc(mp4)
        if fp is None:
            pytest.skip("fpcalc not available")
        assert len(fp.fingerprint) > 0, f"Empty fingerprint for {mp4.name}"
        assert fp.duration > 0.0, f"Zero duration for {mp4.name}"
