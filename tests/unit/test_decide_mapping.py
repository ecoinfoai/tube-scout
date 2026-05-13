"""T029 RED — decide_mapping bucketing unit tests (spec 013).

Covers:
 - high confidence when score >= 65
 - medium confidence when 40 <= score < 65
 - no mapping when score < 40
 - ambiguous when two top candidates tie
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


def _ffprobe_mock(duration: float) -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = f"{duration}"
    proc.stderr = ""
    return proc


def _make_video_meta(
    video_id: str,
    title: str,
    duration_sec: float = 3600.0,
    channel_id: str = "UCfake",
    privacy: str = "unlisted",
    created_at: str = "2026-04-01T09:00:00Z",
) -> "VideoMetadata":
    import datetime
    from tube_scout.models.content import VideoMetadata
    return VideoMetadata(
        video_id=video_id,
        title=title,
        duration_seconds=duration_sec,
        channel_id=channel_id,
        privacy_status=privacy,
        created_at=datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")),
        source="takeout",
        ingested_at=datetime.datetime.now(tz=datetime.timezone.utc),
    )


# ---------------------------------------------------------------------------
# high confidence: score >= 65
# ---------------------------------------------------------------------------

def test_high_confidence_when_score_above_65(tmp_path: Path) -> None:
    """decide_mapping returns confidence='high' when top candidate scores >= 65."""
    from tube_scout.services.evidence_score import decide_mapping

    # mp4 filename matches title exactly (exact=40) + duration within 1s (25) = 65
    title = "1-1.강의제목A"
    mp4 = tmp_path / f"{title}.mp4"
    # File size in plausible range: 1 MB (ratio 1MB/s with duration=1s)
    mp4.write_bytes(b"\x00" * int(1e6))

    videos = [_make_video_meta("vid001", title, duration_sec=1.0)]

    # ffprobe returns 1.0s (matches exactly)
    with patch("subprocess.run", return_value=_ffprobe_mock(duration=1.0)):
        decision = decide_mapping(mp4, videos)

    assert decision.video_id == "vid001", f"Expected vid001, got {decision.video_id}"
    assert decision.confidence == "high", (
        f"Expected 'high', got '{decision.confidence}' (score={decision.score})"
    )
    assert decision.score >= 65, f"Score {decision.score} must be >= 65 for high"


# ---------------------------------------------------------------------------
# medium confidence: 40 <= score < 65
# ---------------------------------------------------------------------------

def test_medium_confidence_when_40_to_65(tmp_path: Path) -> None:
    """decide_mapping returns confidence='medium' when 40 <= score < 65."""
    from tube_scout.services.evidence_score import decide_mapping

    # Only exact title match (40), no duration/size/mtime
    title = "강의제목B"
    mp4 = tmp_path / f"{title}.mp4"
    mp4.write_bytes(b"\x00" * 100)  # tiny — size_ratio_plausible=False

    videos = [_make_video_meta("vid002", title, duration_sec=3600.0)]

    # ffprobe returns 1.0s — far from 3600s → duration_match=False
    with patch("subprocess.run", return_value=_ffprobe_mock(duration=1.0)):
        decision = decide_mapping(mp4, videos)

    assert decision.video_id == "vid002", f"Expected vid002, got {decision.video_id}"
    assert decision.confidence == "medium", (
        f"Expected 'medium', got '{decision.confidence}' (score={decision.score})"
    )
    assert 40 <= decision.score < 65, f"Score {decision.score} must be in [40, 65)"


# ---------------------------------------------------------------------------
# no mapping: score < 40
# ---------------------------------------------------------------------------

def test_no_mapping_when_below_40(tmp_path: Path) -> None:
    """decide_mapping returns video_id=None when best score < medium_threshold."""
    from tube_scout.services.evidence_score import decide_mapping

    # mp4 filename does not match any title (no title signal, no duration)
    mp4 = tmp_path / "완전히다른파일.mp4"
    mp4.write_bytes(b"\x00" * 100)

    videos = [
        _make_video_meta("vid003", "전혀다른제목X", duration_sec=9999.0),
        _make_video_meta("vid004", "전혀다른제목Y", duration_sec=8888.0),
    ]

    with patch("subprocess.run", return_value=_ffprobe_mock(duration=1.0)):
        decision = decide_mapping(mp4, videos)

    assert decision.video_id is None, (
        f"Expected video_id=None for low-score case, got '{decision.video_id}'"
    )
    assert decision.confidence is None, (
        f"Expected confidence=None, got '{decision.confidence}'"
    )
    assert decision.score < 40, f"Score {decision.score} must be < 40"


# ---------------------------------------------------------------------------
# ambiguous: two top candidates tie
# ---------------------------------------------------------------------------

def test_ambiguous_when_two_top_candidates_tie(tmp_path: Path) -> None:
    """decide_mapping returns confidence='ambiguous' when two candidates share top score."""
    from tube_scout.services.evidence_score import decide_mapping

    # Two videos with different IDs but same title (edge case: identical metadata)
    title = "강의제목C"
    mp4 = tmp_path / f"{title}.mp4"
    mp4.write_bytes(b"\x00" * 100)

    videos = [
        _make_video_meta("vid005", title, duration_sec=9999.0),
        _make_video_meta("vid006", title, duration_sec=9999.0),
    ]

    # Both get exact_title_match=True (+40) and same duration mismatch
    with patch("subprocess.run", return_value=_ffprobe_mock(duration=1.0)):
        decision = decide_mapping(mp4, videos)

    assert decision.confidence == "ambiguous", (
        f"Expected 'ambiguous' for tied top scores, got '{decision.confidence}'"
    )
    assert decision.video_id is None, (
        f"Expected video_id=None for ambiguous case, got '{decision.video_id}'"
    )
