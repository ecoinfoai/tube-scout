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


class TestBundleFilterUS1:
    """Tests for US1: report bundle filtering (T005-T008)."""

    def test_bundle_keyword_filter_returns_matching(self, tmp_path: Path) -> None:
        """T005: --keyword filter returns only matching videos in bundle dry-run."""
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
        assert "vid002" not in result.output

    def test_bundle_date_range_filter(self, tmp_path: Path) -> None:
        """T006: date range filter returns only videos in range."""
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
                "--published-after",
                "2026-02-01",
                "--published-before",
                "2026-03-31",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "vid002" in result.output
        assert "vid003" in result.output
        assert "vid001" not in result.output

    def test_bundle_combined_keyword_date_filter(self, tmp_path: Path) -> None:
        """T007: combined keyword + date filter (AND logic)."""
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
                "--published-after",
                "2026-02-01",
                "--published-before",
                "2026-12-31",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "vid003" in result.output
        # vid001 is 감염미생물학 but published 2026-01-15, outside range
        assert "vid001" not in result.output
        assert "vid002" not in result.output

    def test_bundle_empty_filter_result_shows_message(self, tmp_path: Path) -> None:
        """T008: empty filter result shows message and exits with code 0."""
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
                "존재하지않는과목",
            ],
        )

        assert result.exit_code == 0
        assert "No videos matching" in result.output


class TestBundlePreviewUS2:
    """Tests for US2: preview table and confirmation flow (T010-T012)."""

    def test_preview_table_shows_view_count(self, tmp_path: Path) -> None:
        """T010: preview table displays title, published_at, and view_count."""
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
        # view_count values from _VIDEOS: vid001=100, vid003=50
        assert "100" in result.output
        assert "50" in result.output

    def test_no_confirm_skips_interactive(self, tmp_path: Path) -> None:
        """T011: --no-confirm skips typer.confirm and proceeds to generation."""
        proj_dir = _setup_videos_meta(tmp_path)
        app = _make_bundle_app()

        # With --no-confirm, typer.confirm should NOT be called
        with patch("tube_scout.cli.report.typer.confirm") as mock_confirm:
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
                    "--no-confirm",
                ],
            )

        mock_confirm.assert_not_called()
        assert result.exit_code == 0

    def test_dry_run_shows_preview_no_generation(self, tmp_path: Path) -> None:
        """T012: --dry-run shows preview only, no report generation."""
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
        assert "감염미생물학" in result.output
        # No HTML files generated
        bundle_dir = tmp_path / "reports" / "bundle"
        html_files = list(bundle_dir.glob("*.html")) if bundle_dir.exists() else []
        assert len(html_files) == 0


class TestBundleSortUS4:
    """Tests for US4: sort options in bundle command (T032-T034)."""

    def test_sort_date_asc_chronological(self, tmp_path: Path) -> None:
        """T032: --sort date_asc produces chronological order (oldest first)."""
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
                "강의",
                "--sort",
                "date_asc",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        output = result.output
        # vid001 (Jan 15) should come before vid002 (Feb 10) before vid003 (Mar 05)
        pos1 = output.find("vid001")
        pos2 = output.find("vid002")
        pos3 = output.find("vid003")
        assert pos1 < pos2 < pos3

    def test_sort_course_subject_week_order(self, tmp_path: Path) -> None:
        """T033: --sort course produces subject->week order."""
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
                "강의",
                "--sort",
                "course",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        output = result.output
        # 감염미생물학 1주차 (vid001) before 3주차 (vid003)
        # before 인체구조와기능 (vid002)
        pos1 = output.find("vid001")
        pos3 = output.find("vid003")
        pos2 = output.find("vid002")
        assert pos1 < pos3 < pos2

    def test_sort_views_descending(self, tmp_path: Path) -> None:
        """T034: --sort views produces view count descending order."""
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
                "강의",
                "--sort",
                "views",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        output = result.output
        # vid002 (200 views) before vid001 (100) before vid003 (50)
        pos2 = output.find("vid002")
        pos1 = output.find("vid001")
        pos3 = output.find("vid003")
        assert pos2 < pos1 < pos3


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

        # No matching videos → exit 0 with message (not an error).
        # The important thing: no file created outside the data dir.
        assert result.exit_code == 0

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
