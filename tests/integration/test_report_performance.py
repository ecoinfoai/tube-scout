"""Timing benchmark: channel report < 5 min for 500 videos (T105, SC-007)."""

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.video import Video
from tube_scout.reporting.channel_report import ChannelReportGenerator
from tube_scout.reporting.department_report import DepartmentReportGenerator
from tube_scout.storage.json_store import write_json


def _make_synthetic_videos(n: int) -> list[dict[str, Any]]:
    """Generate n synthetic video metadata dicts.

    Args:
        n: Number of videos to generate.

    Returns:
        List of video metadata dicts.
    """
    videos = []
    for i in range(n):
        videos.append({
            "video_id": f"vid_{i:04d}",
            "title": f"Lecture {i}: Introduction to Topic {i % 20}",
            "published_at": f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}T10:00:00Z",
            "view_count": 100 + i * 10,
            "like_count": 5 + i,
            "comment_count": 2 + i % 10,
            "duration_seconds": 600 + (i % 60) * 60,
            "tags": [f"topic_{i % 10}", f"series_{i % 5}"],
            "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
        })
    return videos


class TestReportPerformance:
    """Benchmark: channel report generation under 5 minutes."""

    def test_channel_report_500_videos_under_5_min(
        self, tmp_path: Path
    ) -> None:
        """SC-007: Generate channel report for 500 videos in < 5 min."""
        channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
        data_dir = tmp_path / "data"

        # Set up synthetic data
        channel_dir = data_dir / "raw" / "channels" / channel_id
        channel_dir.mkdir(parents=True, exist_ok=True)

        videos = _make_synthetic_videos(500)
        write_json(channel_dir / "videos_meta.json", videos)
        write_json(channel_dir / "channel_meta.json", {
            "channel_id": channel_id,
            "channel_name": "Test Channel",
            "total_video_count": 500,
        })

        # Create processed dirs (empty — report should handle missing)
        (data_dir / "processed" / "suggestions").mkdir(
            parents=True, exist_ok=True
        )

        generator = ChannelReportGenerator(data_dir=data_dir)
        output_dir = tmp_path / "reports"

        start = time.monotonic()
        result_path = generator.generate(
            channel_id=channel_id, output_dir=output_dir
        )
        elapsed = time.monotonic() - start

        assert result_path.exists()
        assert result_path.suffix == ".html"
        content = result_path.read_text()
        assert len(content) > 0
        assert elapsed < 300, (
            f"Report generation took {elapsed:.1f}s, exceeds 300s limit"
        )

    def test_department_report_3000_videos_under_2_min(
        self, tmp_path: Path,
    ) -> None:
        """SC-004/T048a: Department report for 3000 videos in < 2 min."""
        professors = [f"Prof{i}" for i in range(20)]
        courses = [f"Course{i}" for i in range(30)]

        parsed_titles: list[ParsedTitle] = []
        videos: list[Video] = []
        for i in range(3000):
            vid = f"vid_{i:05d}"
            prof = professors[i % len(professors)]
            course = courses[i % len(courses)]
            week = (i % 16) + 1
            session = (i % 3) + 1

            parsed_titles.append(ParsedTitle(
                video_id=vid,
                original_title=f"{prof} {course} {week}w {session}s",
                professor=[prof],
                course=course,
                year=2026,
                semester=1,
                week=week,
                session=session,
            ))
            videos.append(Video(
                video_id=vid,
                channel_id="UCtest_perf_bench",
                title=f"{prof} {course} {week}w {session}s",
                published_at=datetime(2026, 3, 1),
                duration_seconds=1800 + (i % 600),
                view_count=100 + i,
            ))

        generator = DepartmentReportGenerator()

        start = time.monotonic()
        overview = generator.compute_overview(
            parsed_titles, videos, "UCtest_perf_bench",
        )
        details = generator.compute_professor_details(parsed_titles, videos)
        compliance = generator.compute_compliance(parsed_titles, videos)
        elapsed = time.monotonic() - start

        assert overview.total_videos == 3000
        assert len(details) == 20
        assert len(compliance) == 20
        assert elapsed < 120, (
            f"Department report took {elapsed:.1f}s, exceeds 120s limit"
        )
