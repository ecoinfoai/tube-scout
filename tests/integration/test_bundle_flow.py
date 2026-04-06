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

    def test_100_plus_videos_bundle_generates(self, tmp_path: Path) -> None:
        """T042: 100+ videos bundle generates without memory error."""
        channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
        channel_dir = tmp_path / "raw" / "channels" / channel_id
        channel_dir.mkdir(parents=True, exist_ok=True)

        videos = [
            {
                "video_id": f"vid{i:04d}",
                "channel_id": channel_id,
                "title": f"강의 {i}주차 1차시",
                "published_at": "2026-01-01T00:00:00Z",
                "duration_seconds": 600,
                "view_count": 10,
                "like_count": 1,
                "comment_count": 0,
            }
            for i in range(110)
        ]
        write_json(channel_dir / "videos_meta.json", videos)

        gen = BundleReportGenerator(data_dir=tmp_path)
        video_filter = VideoFilter(keyword="강의")
        output_path = tmp_path / "output" / "bundle.html"

        result = gen.generate(
            video_filter=video_filter,
            channel_id=channel_id,
            output_path=output_path,
        )

        assert result.exists()
        html = result.read_text(encoding="utf-8")
        assert "110" in html  # video count in summary

    def test_e2e_filter_preview_confirm_output(self, tmp_path: Path) -> None:
        """T045: E2E filter -> preview -> confirm -> output."""
        import typer
        from typer.testing import CliRunner

        from tube_scout.cli.report import report_bundle_command
        from tube_scout.storage.json_store import write_json as _write

        channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
        proj_dir = tmp_path / "projects"
        proj = proj_dir / "test_run"
        collect_dir = proj / "01_collect" / "channels" / channel_id
        collect_dir.mkdir(parents=True, exist_ok=True)

        videos = [
            {
                "video_id": f"vid{i:03d}",
                "channel_id": channel_id,
                "title": f"감염미생물학 {i}주차 1차시",
                "published_at": f"2026-01-{i + 1:02d}T10:00:00Z",
                "duration_seconds": 600,
                "view_count": 100 - i,
                "like_count": 5,
                "comment_count": 0,
            }
            for i in range(5)
        ]
        _write(collect_dir / "videos_meta.json", videos)
        _write(
            tmp_path / "config.json",
            {"channels": [{"channel_id": channel_id, "professor_name": "테스트"}]},
        )

        app = typer.Typer()
        app.command(name="bundle")(report_bundle_command)
        cli_runner = CliRunner()

        result = cli_runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--project-dir",
                str(proj_dir),
                "--project",
                str(proj),
                "--keyword",
                "감염미생물학",
                "--sort",
                "date_asc",
                "--format",
                "html",
                "--no-confirm",
            ],
        )

        assert result.exit_code == 0
        assert "5 videos matched" in result.output
        assert "HTML report generated" in result.output
