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


def _setup_full_test_data(data_dir: Path, project_dir: Path) -> tuple[str, Path]:
    """Set up test data with videos_meta, retention, and segments.

    Args:
        data_dir: Config directory (for config.json).
        project_dir: Projects root directory.

    Returns:
        Tuple of (channel_id, project_path).
    """
    channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"

    # Config in data_dir
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

    # Project structure
    proj = project_dir / "test_run"
    collect_dir = proj / "01_collect" / "channels" / channel_id
    collect_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        collect_dir / "videos_meta.json",
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
                "title": "인체구조��기능 2주차 강의",
                "published_at": "2026-02-10T10:00:00Z",
                "duration_seconds": 900,
                "view_count": 200,
                "like_count": 10,
                "comment_count": 2,
            },
            {
                "video_id": "vid003",
                "channel_id": channel_id,
                "title": "감염미생물학 3주차 강��",
                "published_at": "2026-03-05T10:00:00Z",
                "duration_seconds": 500,
                "view_count": 50,
                "like_count": 3,
                "comment_count": 0,
            },
        ],
    )

    # Minimal retention and segments for each video
    analyze_dir = proj / "02_analyze"
    for vid in ["vid001", "vid002", "vid003"]:
        retention_dir = analyze_dir / "retention"
        retention_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            retention_dir / f"{vid}.json",
            {"video_id": vid, "hotspots": [], "skip_zones": []},
        )

        segments_dir = analyze_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            segments_dir / f"{vid}.json",
            [],
        )

    return channel_id, proj


class TestFilteredReportIntegration:
    """Integration test: keyword filter -> only matching videos get reports."""

    def test_keyword_filter_generates_correct_reports(self, tmp_path: Path) -> None:
        """Keyword filter generates reports only for matching videos."""
        project_dir = tmp_path / "projects"
        channel_id, proj = _setup_full_test_data(tmp_path, project_dir)
        out_dir = tmp_path / "output"
        app = _make_app()

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--project-dir",
                str(project_dir),
                "--project",
                str(proj),
                "--keyword",
                "감염미생물학",
                "--output-dir",
                str(out_dir),
            ],
        )

        assert result.exit_code == 0
        # Should generate reports for vid001 and vid003 only
        generated_files = list(out_dir.glob("*.html")) if out_dir.exists() else []
        generated_ids = {f.stem for f in generated_files}
        assert "vid001" in generated_ids
        assert "vid003" in generated_ids
        assert "vid002" not in generated_ids
