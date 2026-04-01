"""Tests for report generators."""

from pathlib import Path

from tube_scout.reporting.video_report import VideoReportGenerator
from tube_scout.storage.json_store import write_json


def _setup_test_data(data_dir: Path) -> None:
    """Set up minimal test data for report generation."""
    channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
    video_id = "vid001"

    # Channel data
    channel_dir = data_dir / "raw" / "channels" / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        channel_dir / "videos_meta.json",
        [
            {
                "video_id": video_id,
                "channel_id": channel_id,
                "title": "Test Lecture",
                "published_at": "2024-01-01T00:00:00Z",
                "duration_seconds": 600,
                "view_count": 1000,
                "like_count": 50,
                "comment_count": 10,
            }
        ],
    )

    # Retention analysis
    retention_dir = data_dir / "processed" / "retention"
    retention_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        retention_dir / f"{video_id}.json",
        {
            "video_id": video_id,
            "hotspots": [{"elapsed_ratio": 0.3, "audience_watch_ratio": 0.9}],
            "skip_zones": [{"elapsed_ratio": 0.7, "audience_watch_ratio": 0.2}],
        },
    )

    # Segments
    segments_dir = data_dir / "processed" / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        segments_dir / f"{video_id}.json",
        [
            {
                "segment_index": 0,
                "title": "Introduction",
                "start_seconds": 0,
                "end_seconds": 120,
                "difficulty_score": 0.3,
            }
        ],
    )


class TestVideoReportGenerator:
    """Tests for VideoReportGenerator (T053)."""

    def test_generate_report_creates_html(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _setup_test_data(data_dir)

        output_dir = data_dir / "reports" / "video"
        output_dir.mkdir(parents=True, exist_ok=True)

        generator = VideoReportGenerator(data_dir=data_dir)
        output_path = generator.generate(
            video_id="vid001",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            output_dir=output_dir,
        )

        assert output_path.exists()
        assert output_path.suffix == ".html"

        content = output_path.read_text()
        # Verify required sections
        assert "vid001" in content
        assert "Test Lecture" in content

    def test_generate_report_with_missing_data(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Only set up minimal video data
        channel_dir = data_dir / "raw" / "channels" / "UCxxxxxxxxxxxxxxxxxxxxxx"
        channel_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            channel_dir / "videos_meta.json",
            [
                {
                    "video_id": "vid002",
                    "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                    "title": "Minimal Lecture",
                    "published_at": "2024-01-01T00:00:00Z",
                    "duration_seconds": 300,
                    "view_count": 500,
                }
            ],
        )

        output_dir = data_dir / "reports" / "video"
        output_dir.mkdir(parents=True, exist_ok=True)

        generator = VideoReportGenerator(data_dir=data_dir)
        output_path = generator.generate(
            video_id="vid002",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            output_dir=output_dir,
        )

        assert output_path.exists()
        content = output_path.read_text()
        assert "vid002" in content
