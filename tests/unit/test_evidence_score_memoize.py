"""T006 — ffprobe memoize tests for score_mp4_candidates (spec 017).

Covers:
 - test_ffprobe_called_once: 3 mp4 files, 10 meta_rows → ffprobe called 3 times total
 - test_cache_injection: passing _ffprobe_cache directly → ffprobe call count == 0
 - test_symlink_shares_cache_entry: absolute / relative / symlink paths to the same
   physical file → ffprobe called exactly once (data-model.md §E-9 Validation)
"""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch


def _make_video_meta(
    video_id: str,
    title: str,
    duration_sec: float = 3600.0,
):  # returns VideoMetadata (local import avoids circular ref at module level)
    from tube_scout.models.content import VideoMetadata
    return VideoMetadata(
        video_id=video_id,
        title=title,
        duration_seconds=duration_sec,
        channel_id="UCfake",
        privacy_status="unlisted",
        created_at=datetime.datetime.fromisoformat("2026-04-01T09:00:00+00:00"),
        source="takeout",
        ingested_at=datetime.datetime.now(tz=datetime.UTC),
    )


def test_ffprobe_called_once(tmp_path: Path) -> None:
    """With 3 mp4 files and 10 meta_rows, ffprobe is called exactly once per mp4 (3 total)."""
    from tube_scout.services.evidence_score import score_mp4_candidates

    mp4_files = []
    for i in range(3):
        mp4 = tmp_path / f"lecture_{i}.mp4"
        mp4.write_bytes(b"\x00" * int(1e6))
        mp4_files.append(mp4)

    meta_rows = [_make_video_meta(f"vid{i:03d}", f"title_{i}") for i in range(10)]

    with patch(
        "tube_scout.services.evidence_score._probe_duration_via_ffprobe",
        return_value=3600.0,
    ) as mock_probe:
        for mp4 in mp4_files:
            score_mp4_candidates(mp4, meta_rows, _ffprobe_cache={})

    assert mock_probe.call_count == 3, (
        f"Expected ffprobe called 3 times (once per mp4), got {mock_probe.call_count}"
    )


def test_cache_injection(tmp_path: Path) -> None:
    """Passing a pre-populated _ffprobe_cache (resolve()-keyed) results in 0 ffprobe calls."""
    from tube_scout.services.evidence_score import score_mp4_candidates

    mp4 = tmp_path / "lecture.mp4"
    mp4.write_bytes(b"\x00" * int(1e6))

    meta_rows = [_make_video_meta(f"vid{i:03d}", f"title_{i}") for i in range(10)]

    pre_cache = {str(mp4.resolve()): 3600.0}

    with patch(
        "tube_scout.services.evidence_score._probe_duration_via_ffprobe",
        return_value=3600.0,
    ) as mock_probe:
        score_mp4_candidates(mp4, meta_rows, _ffprobe_cache=pre_cache)

    assert mock_probe.call_count == 0, (
        f"Expected 0 ffprobe calls with pre-populated cache, got {mock_probe.call_count}"
    )


def test_symlink_shares_cache_entry(tmp_path: Path) -> None:
    """Absolute, cwd-relative, and symlink paths to the same physical mp4 share one cache entry.

    data-model.md §E-9 Validation: cache key is str(path.resolve()) so symlinks
    to the same file produce the same key and ffprobe is called only once.
    """
    from tube_scout.services.evidence_score import score_mp4_candidates

    # create the physical mp4
    mp4_abs = tmp_path / "real_lecture.mp4"
    mp4_abs.write_bytes(b"\x00" * int(1e6))

    # create a symlink pointing to the same file
    mp4_symlink = tmp_path / "link_lecture.mp4"
    mp4_symlink.symlink_to(mp4_abs)

    meta_rows = [_make_video_meta("vid001", "title_1")]

    shared_cache: dict[str, float | None] = {}

    with patch(
        "tube_scout.services.evidence_score._probe_duration_via_ffprobe",
        return_value=3600.0,
    ) as mock_probe:
        # call via absolute path — populates cache
        score_mp4_candidates(mp4_abs, meta_rows, _ffprobe_cache=shared_cache)
        # call via symlink path — must hit same cache entry (resolve() collapses symlink)
        score_mp4_candidates(mp4_symlink, meta_rows, _ffprobe_cache=shared_cache)

    assert mock_probe.call_count == 1, (
        f"Expected ffprobe called once for both absolute and symlink paths, "
        f"got {mock_probe.call_count}"
    )
    assert len(shared_cache) == 1, (
        f"Expected 1 cache entry for the same physical file, got {len(shared_cache)}"
    )
