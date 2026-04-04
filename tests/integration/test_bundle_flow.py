"""Integration test for bundle report flow (T016)."""

from pathlib import Path

from tube_scout.models.video_filter import VideoFilter
from tube_scout.reporting.bundle_report import BundleReportGenerator
from tube_scout.storage.json_store import write_json


def _setup_bundle_data(data_dir: Path) -> str:
    """Set up full test data for bundle flow.

    Returns:
        The channel_id used.
    """
    channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
    channel_dir = data_dir / "raw" / "channels" / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        channel_dir / "videos_meta.json",
        [
            {
                "video_id": "vid001",
                "channel_id": channel_id,
                "title": "감염미생물학 1주차 강의",
                "published_at": "2026-01-15T10:00:00Z",
                "duration_seconds": 600,
                "view_count": 100,
                "like_count": 5,
                "comment_count": 1,
            },
            {
                "video_id": "vid002",
                "channel_id": channel_id,
                "title": "인체구조와기능 2주차 강의",
                "published_at": "2026-02-10T10:00:00Z",
                "duration_seconds": 900,
                "view_count": 200,
                "like_count": 10,
                "comment_count": 2,
            },
            {
                "video_id": "vid003",
                "channel_id": channel_id,
                "title": "감염미생물학 3주차 강의",
                "published_at": "2026-03-05T10:00:00Z",
                "duration_seconds": 500,
                "view_count": 50,
                "like_count": 3,
                "comment_count": 0,
            },
        ],
    )

    for vid in ["vid001", "vid002", "vid003"]:
        retention_dir = data_dir / "processed" / "retention"
        retention_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            retention_dir / f"{vid}.json",
            {"video_id": vid, "hotspots": [], "skip_zones": []},
        )
        segments_dir = data_dir / "processed" / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)
        write_json(segments_dir / f"{vid}.json", [])

    return channel_id


class TestBundleFlow:
    """Integration: VideoFilter -> BundleReportGenerator -> HTML output."""

    def test_filtered_bundle_generates_html(self, tmp_path: Path) -> None:
        """Bundle generation with keyword filter produces correct HTML."""
        channel_id = _setup_bundle_data(tmp_path)
        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="감염미생물학")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        assert result.exists()
        html = result.read_text(encoding="utf-8")
        # Should contain only filtered videos
        assert "감염미생물학 1주차 강의" in html
        assert "감염미생물학 3주차 강의" in html
        assert "인체구조와기능" not in html
