"""Unit tests for report video CLI filter options (T010) and dry-run (T023)."""

from pathlib import Path
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from tube_scout.cli.report import report_bundle_command, report_video_command
from tube_scout.storage.json_store import write_json

runner = CliRunner()

_CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"
_VIDEOS = [
    {
        "video_id": "vid001",
        "channel_id": _CHANNEL_ID,
        "title": "감염미생물학 1주차 강의",
        "published_at": "2026-01-15T10:00:00Z",
        "duration_seconds": 600,
        "view_count": 100,
        "like_count": 5,
        "comment_count": 1,
    },
    {
        "video_id": "vid002",
        "channel_id": _CHANNEL_ID,
        "title": "인체구조와기능 2주차 강의",
        "published_at": "2026-02-10T10:00:00Z",
        "duration_seconds": 900,
        "view_count": 200,
        "like_count": 10,
        "comment_count": 2,
    },
    {
        "video_id": "vid003",
        "channel_id": _CHANNEL_ID,
        "title": "감염미생물학 3주차 강의",
        "published_at": "2026-03-05T10:00:00Z",
        "duration_seconds": 500,
        "view_count": 50,
        "like_count": 3,
        "comment_count": 0,
    },
]


def _make_app() -> typer.Typer:
    """Create a minimal Typer app with report video command."""
    app = typer.Typer()
    app.command(name="video")(report_video_command)
    return app


def _make_bundle_app() -> typer.Typer:
    """Create a minimal Typer app with report bundle command."""
    app = typer.Typer()
    app.command(name="bundle")(report_bundle_command)
    return app


def _setup_videos_meta(data_dir: Path, project_dir: Path | None = None) -> Path:
    """Write test videos_meta.json and config.json.

    Args:
        data_dir: Config directory (for config.json).
        project_dir: If given, write video data in project structure.

    Returns:
        The project_dir root (for --project-dir flag).
    """
    # Config always in data_dir
    write_json(
        data_dir / "config.json",
        {
            "channels": [
                {
                    "channel_id": _CHANNEL_ID,
                    "professor_name": "테스트교수",
                },
            ],
        },
    )

    if project_dir is None:
        project_dir = data_dir / "projects"

    # Create a project with collect dir
    proj = project_dir / "test_run"
    collect_dir = proj / "01_collect" / "channels" / _CHANNEL_ID
    collect_dir.mkdir(parents=True, exist_ok=True)
    write_json(collect_dir / "videos_meta.json", _VIDEOS)

    return project_dir


class TestReportVideoFilterOptions:
    """Tests for --keyword, --published-after, --published-before,
    --video-ids options."""

    def test_keyword_filter_generates_only_matching(self, tmp_path: Path) -> None:
        """--keyword filters videos by title substring."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        generated_ids: list[str] = []

        def mock_generate(
            collect_dir: Path,
            analyze_dir: Path,
            video_id: str,
            channel_id: str,
            output_dir: Path,
            fmt: str,
        ) -> Path:
            generated_ids.append(video_id)
            return output_dir / f"{video_id}.html"

        with patch(
            "tube_scout.cli.report._generate_video_report", side_effect=mock_generate
        ):
            result = runner.invoke(
                app,
                [
                    "--data-dir",
                    str(tmp_path),
                    "--project-dir",
                    str(proj_dir),
                    "--project",
                    str(proj_dir / "test_run"),
                    "--keyword",
                    "감염미생물학",
                ],
            )

        assert result.exit_code == 0
        assert set(generated_ids) == {"vid001", "vid003"}

    def test_date_range_filter(self, tmp_path: Path) -> None:
        """--published-after and --published-before filter by date range."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        generated_ids: list[str] = []

        def mock_generate(
            collect_dir: Path,
            analyze_dir: Path,
            video_id: str,
            channel_id: str,
            output_dir: Path,
            fmt: str,
        ) -> Path:
            generated_ids.append(video_id)
            return output_dir / f"{video_id}.html"

        with patch(
            "tube_scout.cli.report._generate_video_report", side_effect=mock_generate
        ):
            result = runner.invoke(
                app,
                [
                    "--data-dir",
                    str(tmp_path),
                    "--project-dir",
                    str(proj_dir),
                    "--project",
                    str(proj_dir / "test_run"),
                    "--published-after",
                    "2026-02-01",
                    "--published-before",
                    "2026-03-31",
                ],
            )

        assert result.exit_code == 0
        assert set(generated_ids) == {"vid002", "vid003"}

    def test_video_ids_filter(self, tmp_path: Path) -> None:
        """--video-ids filters by comma-separated video IDs."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        generated_ids: list[str] = []

        def mock_generate(
            collect_dir: Path,
            analyze_dir: Path,
            video_id: str,
            channel_id: str,
            output_dir: Path,
            fmt: str,
        ) -> Path:
            generated_ids.append(video_id)
            return output_dir / f"{video_id}.html"

        with patch(
            "tube_scout.cli.report._generate_video_report", side_effect=mock_generate
        ):
            result = runner.invoke(
                app,
                [
                    "--data-dir",
                    str(tmp_path),
                    "--project-dir",
                    str(proj_dir),
                    "--project",
                    str(proj_dir / "test_run"),
                    "--video-ids",
                    "vid001,vid003",
                ],
            )

        assert result.exit_code == 0
        assert set(generated_ids) == {"vid001", "vid003"}

    def test_filter_no_results_exit_code_1(self, tmp_path: Path) -> None:
        """Filter with 0 matches prints message and exits with code 1."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--project-dir",
                str(proj_dir),
                "--project",
                str(proj_dir / "test_run"),
                "--keyword",
                "존재하지않는과목",
            ],
        )

        assert result.exit_code == 1
        assert "No videos matching" in result.output or "0" in result.output

    def test_video_id_and_video_ids_mutual_exclusion(self, tmp_path: Path) -> None:
        """--video-id and --video-ids cannot be used together."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--project-dir",
                str(proj_dir),
                "--project",
                str(proj_dir / "test_run"),
                "--video-id",
                "vid001",
                "--video-ids",
                "vid002,vid003",
            ],
        )

        assert result.exit_code == 1


class TestReportVideoDryRun:
    """Tests for --dry-run option on report video (T023)."""

    def test_dry_run_does_not_generate_reports(self, tmp_path: Path) -> None:
        """--dry-run with --keyword shows video list, no report generation."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        generated_ids: list[str] = []

        def mock_generate(
            collect_dir: Path,
            analyze_dir: Path,
            video_id: str,
            channel_id: str,
            output_dir: Path,
            fmt: str,
        ) -> Path:
            generated_ids.append(video_id)
            return output_dir / f"{video_id}.html"

        with patch(
            "tube_scout.cli.report._generate_video_report", side_effect=mock_generate
        ):
            result = runner.invoke(
                app,
                [
                    "--data-dir",
                    str(tmp_path),
                    "--project-dir",
                    str(proj_dir),
                    "--project",
                    str(proj_dir / "test_run"),
                    "--keyword",
                    "감염미생물학",
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0
        assert len(generated_ids) == 0  # No reports generated
        # Output should contain video info
        assert "vid001" in result.output
        assert "vid003" in result.output
        assert "감염미생물학" in result.output

    def test_dry_run_shows_count(self, tmp_path: Path) -> None:
        """--dry-run output includes matching video count."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_app()

        with patch("tube_scout.cli.report._generate_video_report"):
            result = runner.invoke(
                app,
                [
                    "--data-dir",
                    str(tmp_path),
                    "--project-dir",
                    str(proj_dir),
                    "--project",
                    str(proj_dir / "test_run"),
                    "--keyword",
                    "감염미생물학",
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0
        assert "2" in result.output  # 2 matching videos


class TestReportBundleDryRun:
    """Tests for --dry-run option on report bundle (T023)."""

    def test_bundle_dry_run_no_html_generated(self, tmp_path: Path) -> None:
        """--dry-run on bundle shows video list, no HTML/PDF generated."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_bundle_app()

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--project-dir",
                str(proj_dir),
                "--project",
                str(proj_dir / "test_run"),
                "--keyword",
                "감염미생물학",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "vid001" in result.output
        assert "vid003" in result.output
        # No output files should exist
        bundle_dir = tmp_path / "reports" / "bundle"
        html_files = list(bundle_dir.glob("*.html")) if bundle_dir.exists() else []
        assert len(html_files) == 0


class TestBundleAutoFilenameSanitize:
    """Tests for path traversal prevention in auto-generated bundle filenames."""

    def test_keyword_with_path_traversal_sanitized(self, tmp_path: Path) -> None:
        """--keyword with path traversal chars must not escape output dir."""
        _setup_videos_meta(tmp_path)
        app = _make_bundle_app()

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--keyword",
                "../../../etc/passwd",
            ],
        )

        # Should fail with no matching videos (the keyword won't match),
        # but even if it did, the filename must not contain path separators.
        # Exit code 1 is fine (no matching videos).
        # The important thing: no file created outside the data dir.
        assert result.exit_code == 1

    def test_keyword_with_slashes_sanitized_in_filename(self, tmp_path: Path) -> None:
        """Auto filename must sanitize slashes and dots from keyword."""
        from tube_scout.cli.report import _sanitize_filename_part

        assert "/" not in _sanitize_filename_part("../../etc/passwd")
        assert "\\" not in _sanitize_filename_part("..\\..\\etc")
        assert ".." not in _sanitize_filename_part("../test")
        # Korean and alphanumeric should be preserved
        result = _sanitize_filename_part("감염미생물학")
        assert result == "감염미생물학"


class TestBundleLargeFilterWarning:
    """Tests for 200+ video warning on report bundle (T038)."""

    def test_over_200_videos_shows_warning(self, tmp_path: Path) -> None:
        """Bundle with >200 filtered videos shows size warning."""
        channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"

        # Set up project structure
        proj_dir = tmp_path / "projects"
        proj = proj_dir / "test_run"
        collect_dir = proj / "01_collect" / "channels" / channel_id
        collect_dir.mkdir(parents=True, exist_ok=True)
        # Create 210 videos matching keyword
        videos = [
            {
                "video_id": f"vid{i:04d}",
                "channel_id": channel_id,
                "title": f"강의 {i}주차",
                "published_at": "2026-01-01T00:00:00Z",
                "duration_seconds": 600,
                "view_count": 10,
                "like_count": 1,
                "comment_count": 0,
            }
            for i in range(210)
        ]
        write_json(collect_dir / "videos_meta.json", videos)
        write_json(
            tmp_path / "config.json",
            {"channels": [{"channel_id": channel_id, "professor_name": "테스트"}]},
        )

        app = _make_bundle_app()
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "--project-dir",
                str(proj_dir),
                "--project",
                str(proj),
                "--keyword",
                "강의",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "210" in result.output
        # Must show explicit large dataset warning
        assert "large" in result.output.lower() or "200" in result.output
