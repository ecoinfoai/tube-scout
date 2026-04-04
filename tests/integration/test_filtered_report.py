"""Integration test for filtered report generation (T011)."""

from pathlib import Path

import typer
from typer.testing import CliRunner

from tube_scout.cli.report import report_video_command
from tube_scout.storage.json_store import write_json

runner = CliRunner()


def _make_app() -> typer.Typer:
    """Create a minimal Typer app with report video command."""
    app = typer.Typer()
    app.command(name="video")(report_video_command)
    return app


def _setup_full_test_data(data_dir: Path) -> str:
    """Set up test data with videos_meta, retention, and segments.

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

    write_json(
        data_dir / "config.json",
        {
            "channels": [
                {
                    "channel_id": channel_id,
                    "professor_name": "테스트교수",
                },
            ],
        },
    )

    # Minimal retention and segments for each video
    for vid in ["vid001", "vid002", "vid003"]:
        retention_dir = data_dir / "processed" / "retention"
        retention_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            retention_dir / f"{vid}.json",
            {"video_id": vid, "hotspots": [], "skip_zones": []},
        )

        segments_dir = data_dir / "processed" / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            segments_dir / f"{vid}.json",
            [],
        )

    return channel_id


class TestFilteredReportIntegration:
    """Integration test: keyword filter -> only matching videos get reports."""

    def test_keyword_filter_generates_correct_reports(self, tmp_path: Path) -> None:
        """Keyword filter generates reports only for matching videos."""
        _setup_full_test_data(tmp_path)
        out_dir = tmp_path / "output"
        app = _make_app()

        result = runner.invoke(app, [
            "--data-dir", str(tmp_path),
            "--keyword", "감염미생물학",
            "--output-dir", str(out_dir),
        ])

        assert result.exit_code == 0
        # Should generate reports for vid001 and vid003 only
        generated_files = list(out_dir.glob("*.html")) if out_dir.exists() else []
        generated_ids = {f.stem for f in generated_files}
        assert "vid001" in generated_ids
        assert "vid003" in generated_ids
        assert "vid002" not in generated_ids
