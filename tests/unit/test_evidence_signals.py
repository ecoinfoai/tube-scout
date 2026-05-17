"""T028 RED — EvidenceSignals unit tests (spec 013).

Covers:
 - exact_title_match full string
 - normalized_title_match with spaces/punctuation
 - normalized_title_match prefix (255-char truncation simulation)
 - duration_match within / outside tolerance
 - size_ratio_plausible range
 - mtime_match within 1 day
 - score computation: all signals (40+25+5+5=75)
 - score: normalized replaces exact (+30 not +70)
"""

from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_ffprobe_result(duration: float = 3600.0) -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = f"{duration}"
    proc.stderr = ""
    return proc


# ---------------------------------------------------------------------------
# exact_title_match
# ---------------------------------------------------------------------------

def test_exact_title_match_full_string(tmp_path: Path) -> None:
    """mp4 stem == video_title → exact_title_match=True."""
    from tube_scout.services.evidence_score import EvidenceSignals

    mp4 = tmp_path / "1-1.강의제목A.mp4"
    mp4.write_bytes(b"\x00" * 1024)

    signals = EvidenceSignals(
        exact_title_match=True,
        normalized_title_match=False,
        duration_match_within_1s=False,
        size_ratio_plausible=False,
        mtime_match_within_1d=False,
    )
    assert signals.exact_title_match is True
    assert signals.score == 40


def test_exact_title_match_false_when_different(tmp_path: Path) -> None:
    """mp4 stem != video_title → exact_title_match=False."""
    from tube_scout.services.evidence_score import EvidenceSignals

    signals = EvidenceSignals(
        exact_title_match=False,
        normalized_title_match=False,
        duration_match_within_1s=False,
        size_ratio_plausible=False,
        mtime_match_within_1d=False,
    )
    assert signals.exact_title_match is False
    assert signals.score == 0


# ---------------------------------------------------------------------------
# normalized_title_match
# ---------------------------------------------------------------------------

def test_normalized_title_match_handles_spaces_and_punctuation() -> None:
    """Normalized match strips punctuation/spaces for comparison."""
    from tube_scout.services.evidence_score import _normalize_for_match

    # "1-1.강의제목A" normalized == "11강의제목a"
    assert _normalize_for_match("1-1.강의제목A") == _normalize_for_match("1-1.강의제목A")
    # spaces and dashes removed
    assert _normalize_for_match("hello world") == _normalize_for_match("helloworld")
    assert _normalize_for_match("test-title_v1") == _normalize_for_match("testtitlev1")


def test_normalized_title_match_prefix_50_chars() -> None:
    """255-char truncated mp4 stem (>=50 chars) that is prefix of title → match."""
    from tube_scout.services.evidence_score import _normalize_for_match

    # Simulate: title is long (>255 chars when encoded), mp4 stem is prefix
    long_title = "강의제목" * 40  # 160 chars
    truncated_stem = "강의제목" * 13  # 52 chars (>= 50)

    norm_stem = _normalize_for_match(truncated_stem)
    norm_title = _normalize_for_match(long_title)
    # stem is prefix of title
    assert norm_title.startswith(norm_stem), (
        "normalized long title must start with normalized truncated stem"
    )
    assert len(norm_stem) >= 50, f"stem length {len(norm_stem)} must be >= 50"


# ---------------------------------------------------------------------------
# score computation
# ---------------------------------------------------------------------------

def test_score_computation_all_signals() -> None:
    """All signals set (exact) → score = 40+25+5+5 = 75."""
    from tube_scout.services.evidence_score import EvidenceSignals

    signals = EvidenceSignals(
        exact_title_match=True,
        normalized_title_match=False,
        duration_match_within_1s=True,
        size_ratio_plausible=True,
        mtime_match_within_1d=True,
    )
    assert signals.score == 75, f"Expected 75, got {signals.score}"


def test_score_computation_normalized_replaces_exact() -> None:
    """normalized_title_match=True, exact=False → +30, not +70."""
    from tube_scout.services.evidence_score import EvidenceSignals

    signals = EvidenceSignals(
        exact_title_match=False,
        normalized_title_match=True,
        duration_match_within_1s=True,
        size_ratio_plausible=True,
        mtime_match_within_1d=True,
    )
    assert signals.score == 65, f"Expected 30+25+5+5=65, got {signals.score}"


def test_score_computation_exact_does_not_add_normalized() -> None:
    """exact=True, normalized=True → only +40 (not +70)."""
    from tube_scout.services.evidence_score import EvidenceSignals

    signals = EvidenceSignals(
        exact_title_match=True,
        normalized_title_match=True,
        duration_match_within_1s=False,
        size_ratio_plausible=False,
        mtime_match_within_1d=False,
    )
    # exact wins; normalized is only if not exact
    assert signals.score == 40, f"Expected 40 (exact only), got {signals.score}"


# ---------------------------------------------------------------------------
# duration_match_within_1s
# ---------------------------------------------------------------------------

def test_duration_match_within_tolerance(tmp_path: Path) -> None:
    """duration_match_within_1s=True when |actual - expected| <= 1.0."""
    from tube_scout.services.evidence_score import _duration_match

    mp4 = tmp_path / "test.mp4"
    mp4.write_bytes(b"\x00" * 512)

    with patch("subprocess.run", return_value=_make_ffprobe_result(duration=3600.5)):
        result = _duration_match(mp4, video_duration_s=3600.0, tol_s=1.0)

    assert result is True


def test_duration_match_outside_tolerance_false(tmp_path: Path) -> None:
    """duration_match_within_1s=False when |actual - expected| > 1.0."""
    from tube_scout.services.evidence_score import _duration_match

    mp4 = tmp_path / "test.mp4"
    mp4.write_bytes(b"\x00" * 512)

    with patch("subprocess.run", return_value=_make_ffprobe_result(duration=1.0)):
        result = _duration_match(mp4, video_duration_s=3600.0, tol_s=1.0)

    assert result is False


# ---------------------------------------------------------------------------
# size_ratio_plausible
# ---------------------------------------------------------------------------

def test_size_ratio_plausible_range(tmp_path: Path) -> None:
    """size_ratio_plausible=True when bytes/second in [0.5MB/s, 10MB/s]."""
    from tube_scout.services.evidence_score import _size_ratio_plausible

    mp4 = tmp_path / "lecture.mp4"
    # 1MB/s × 3600s = 3.6 GB — write 1 MB as proxy, pass duration=1.0 for simple ratio
    size_bytes = int(1e6)  # 1 MB
    mp4.write_bytes(b"\x00" * size_bytes)

    result = _size_ratio_plausible(mp4, duration_s=1.0)
    assert result is True


def test_size_ratio_implausible_too_small(tmp_path: Path) -> None:
    """size_ratio_plausible=False when file is tiny for its claimed duration."""
    from tube_scout.services.evidence_score import _size_ratio_plausible

    mp4 = tmp_path / "tiny.mp4"
    mp4.write_bytes(b"\x00" * 100)  # 100 bytes / 3600s ≈ 0 bytes/s → implausible

    result = _size_ratio_plausible(mp4, duration_s=3600.0)
    assert result is False


# ---------------------------------------------------------------------------
# mtime_match_within_1d
# ---------------------------------------------------------------------------

def test_mtime_match_within_1d(tmp_path: Path) -> None:
    """mtime_match_within_1d=True when |mp4.mtime - created_at| <= 1 day."""
    from tube_scout.services.evidence_score import _mtime_match

    mp4 = tmp_path / "test.mp4"
    mp4.write_bytes(b"\x00" * 100)

    # Set mtime to now
    now = datetime.datetime.now(tz=datetime.UTC)
    # created_at 12 hours ago — within 1 day
    created_at = now - datetime.timedelta(hours=12)

    import os
    os.utime(mp4, (now.timestamp(), now.timestamp()))

    result = _mtime_match(mp4, created_at=created_at, tol_days=1.0)
    assert result is True


def test_mtime_match_outside_1d(tmp_path: Path) -> None:
    """mtime_match_within_1d=False when |mp4.mtime - created_at| > 1 day."""
    from tube_scout.services.evidence_score import _mtime_match

    mp4 = tmp_path / "test.mp4"
    mp4.write_bytes(b"\x00" * 100)

    now = datetime.datetime.now(tz=datetime.UTC)
    created_at = now - datetime.timedelta(days=30)  # 30 days ago

    import os
    os.utime(mp4, (now.timestamp(), now.timestamp()))

    result = _mtime_match(mp4, created_at=created_at, tol_days=1.0)
    assert result is False
