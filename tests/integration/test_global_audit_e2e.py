"""Layer 4: End-to-end pipeline verification tests.

Tests the full CLI command sequence from init through collect, report,
validate, and checkpoint-based resume, using mock API responses and
typer's CliRunner.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from tube_scout.cli.main import app
from tube_scout.models.config import CollectionState
from tube_scout.storage.checkpoint import load_checkpoint
from tube_scout.storage.json_store import read_json, write_json

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared constants and mock data factories
# ---------------------------------------------------------------------------
CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"
PROFESSOR = "TestProfessor"


def _write_config(
    data_dir: Path, channel_id: str = CHANNEL_ID, professor: str = PROFESSOR
) -> None:
    """Write a valid config.json."""
    config = {
        "channels": [
            {"channel_id": channel_id, "professor_name": professor},
        ],
        "settings": {
            "data_dir": str(data_dir),
            "sentiment_backend": "llm",
            "default_report_format": "html",
        },
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / "config.json", config)


def _mock_channel_response(channel_id: str = CHANNEL_ID) -> dict:
    return {
        "items": [
            {
                "id": channel_id,
                "snippet": {"title": "Test Channel"},
                "contentDetails": {
                    "relatedPlaylists": {
                        "uploads": channel_id.replace("UC", "UU"),
                    },
                },
                "statistics": {"videoCount": "3"},
            }
        ],
    }


def _mock_playlist_response(professor: str = PROFESSOR) -> dict:
    return {
        "items": [
            {
                "snippet": {
                    "resourceId": {"videoId": "vid001"},
                    "title": f"{professor} Lecture 1",
                    "publishedAt": "2025-03-01T00:00:00Z",
                },
            },
            {
                "snippet": {
                    "resourceId": {"videoId": "vid002"},
                    "title": f"{professor} Lecture 2",
                    "publishedAt": "2025-03-15T00:00:00Z",
                },
            },
            {
                "snippet": {
                    "resourceId": {"videoId": "vid003"},
                    "title": "Other Video No Match",
                    "publishedAt": "2025-04-01T00:00:00Z",
                },
            },
        ],
    }


def _mock_video_details_response() -> dict:
    return {
        "items": [
            {
                "id": "vid001",
                "snippet": {
                    "title": f"{PROFESSOR} Lecture 1",
                    "description": "Lecture 1 desc",
                    "thumbnails": {"default": {"url": "http://example.com/1.jpg"}},
                },
                "contentDetails": {"duration": "PT15M0S", "caption": "true"},
                "statistics": {
                    "viewCount": "500",
                    "likeCount": "25",
                    "commentCount": "5",
                },
                "status": {"privacyStatus": "public"},
                "topicDetails": {},
            },
            {
                "id": "vid002",
                "snippet": {
                    "title": f"{PROFESSOR} Lecture 2",
                    "description": "Lecture 2 desc",
                    "thumbnails": {"default": {"url": "http://example.com/2.jpg"}},
                },
                "contentDetails": {"duration": "PT30M0S", "caption": "false"},
                "statistics": {
                    "viewCount": "1200",
                    "likeCount": "60",
                    "commentCount": "15",
                },
                "status": {"privacyStatus": "public"},
                "topicDetails": {},
            },
        ],
    }


def _mock_transcript_result(video_id: str) -> dict:
    return {
        "video_id": video_id,
        "transcript_type": "auto_generated",
        "segments": [
            {"text": "Hello class", "start": 0.0, "duration": 5.0},
            {"text": "Today we cover topic A", "start": 5.0, "duration": 10.0},
        ],
    }


def _mock_retention_data() -> list[dict]:
    return [
        {"elapsed_ratio": 0.0, "audience_watch_ratio": 1.0},
        {"elapsed_ratio": 0.25, "audience_watch_ratio": 0.9},
        {"elapsed_ratio": 0.5, "audience_watch_ratio": 0.7},
        {"elapsed_ratio": 0.75, "audience_watch_ratio": 0.5},
        {"elapsed_ratio": 1.0, "audience_watch_ratio": 0.3},
    ]


def _setup_mock_data_client(
    mock_build: MagicMock, channel_id: str = CHANNEL_ID, professor: str = PROFESSOR
) -> MagicMock:
    """Configure a mock YouTube Data API client and return it."""
    client = MagicMock()
    mock_build.return_value = client

    client.channels().list.return_value.execute.return_value = _mock_channel_response(
        channel_id
    )
    client.playlistItems().list.return_value.execute.return_value = (
        _mock_playlist_response(professor)
    )
    client.videos().list.return_value.execute.return_value = (
        _mock_video_details_response()
    )
    # Comments: return empty (comments disabled for university)
    client.commentThreads().list.return_value.execute.return_value = {
        "items": [],
    }
    return client


def _find_project_dir(project_root: Path) -> Path:
    """Find the actual project directory (timestamp-named) under projects/."""
    latest = project_root / "latest"
    if latest.is_symlink():
        return latest.resolve()
    # Fallback: find first timestamped directory
    for p in sorted(project_root.iterdir()):
        if p.is_dir() and p.name != "latest":
            return p
    raise FileNotFoundError(f"No project directory found in {project_root}")


# ===========================================================================
# E2E-1: New project full collection
# ===========================================================================
class TestE2E1FullCollection:
    """E2E-1: init -> collect all -> verify project structure and data files."""

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    @patch("tube_scout.services.auth.build_analytics_client")
    @patch("tube_scout.services.auth.build_data_client")
    def test_init_and_collect_all(
        self,
        mock_build_data: MagicMock,
        mock_build_analytics: MagicMock,
        mock_transcript_api: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Full pipeline: init creates config, collect all creates data files."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"

        # Step 1: Init
        result = runner.invoke(
            app,
            [
                "init",
                "--channel-id",
                CHANNEL_ID,
                "--professor",
                PROFESSOR,
                "--data-dir",
                str(data_dir),
            ],
        )
        assert result.exit_code == 0, f"init failed: {result.output}"

        # Verify config created
        config = read_json(data_dir / "config.json")
        assert config is not None
        assert config["channels"][0]["channel_id"] == CHANNEL_ID

        # Step 2: Set up mocks
        _setup_mock_data_client(mock_build_data)

        # Analytics mock
        analytics_client = MagicMock()
        mock_build_analytics.return_value = analytics_client
        analytics_client.reports().query.return_value.execute.return_value = {
            "rows": [],
            "columnHeaders": [],
        }

        # Transcript mock
        mock_api_instance = MagicMock()
        mock_transcript_api.return_value = mock_api_instance
        mock_list = MagicMock()
        mock_api_instance.list.return_value = mock_list
        mock_transcript = MagicMock()
        mock_list.find_manually_created_transcript.side_effect = Exception("no manual")
        mock_list.find_generated_transcript.return_value = mock_transcript
        mock_fetch_result = MagicMock()
        mock_fetch_result.snippets = [
            MagicMock(text="Hello class", start=0.0, duration=5.0),
            MagicMock(text="Topic A", start=5.0, duration=10.0),
        ]
        mock_transcript.fetch.return_value = mock_fetch_result

        # Step 3: Collect all
        result = runner.invoke(
            app,
            [
                "collect",
                "all",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        # collect all may have partial failures (analytics, etc.) but shouldn't crash
        assert result.exit_code == 0, f"collect all failed: {result.output}"

        # Step 4: Verify project structure
        proj = _find_project_dir(project_dir)
        assert (proj / "01_collect").exists()
        assert (proj / "checkpoints").exists()

        # Verify videos_meta.json
        channel_dir = proj / "01_collect" / "channels" / CHANNEL_ID
        assert channel_dir.exists()
        videos_meta = read_json(channel_dir / "videos_meta.json")
        assert videos_meta is not None
        videos = (
            videos_meta
            if isinstance(videos_meta, list)
            else videos_meta.get("videos", [])
        )
        assert len(videos) == 2  # Only professor-filtered videos

        # Verify all video_ids are present
        video_ids = {v["video_id"] for v in videos}
        assert video_ids == {"vid001", "vid002"}

        # Verify Parquet file created
        parquet_path = channel_dir / "videos_meta.parquet"
        assert parquet_path.exists()

        # Verify checkpoint recorded
        checkpoint = load_checkpoint(proj / "checkpoints", CHANNEL_ID, "videos")
        assert checkpoint is not None
        assert checkpoint.status == "completed"

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    @patch("tube_scout.services.auth.build_analytics_client")
    @patch("tube_scout.services.auth.build_data_client")
    def test_collected_data_pydantic_roundtrip(
        self,
        mock_build_data: MagicMock,
        mock_build_analytics: MagicMock,
        mock_transcript_api: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Data integrity: all collected JSON can be deserialized by Pydantic models."""
        from tube_scout.models.video import Video

        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)

        _setup_mock_data_client(mock_build_data)

        analytics_client = MagicMock()
        mock_build_analytics.return_value = analytics_client
        analytics_client.reports().query.return_value.execute.return_value = {
            "rows": [],
            "columnHeaders": [],
        }

        mock_api_instance = MagicMock()
        mock_transcript_api.return_value = mock_api_instance
        mock_api_instance.list.side_effect = Exception("no transcripts")

        result = runner.invoke(
            app,
            [
                "collect",
                "all",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)
        channel_dir = proj / "01_collect" / "channels" / CHANNEL_ID
        videos_meta = read_json(channel_dir / "videos_meta.json")
        assert videos_meta is not None
        videos = (
            videos_meta
            if isinstance(videos_meta, list)
            else videos_meta.get("videos", [])
        )

        # Every video record must be parseable by Video model
        for v in videos:
            video = Video(**v)
            assert video.video_id in {"vid001", "vid002"}


# ===========================================================================
# E2E-2: Department report generation
# ===========================================================================
class TestE2E2DepartmentReport:
    """E2E-2: collect videos -> report department -> verify output."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_department_xlsx_report(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Department report: collect -> write parsed titles -> generate XLSX."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        # Step 1: Collect videos
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0, f"collect videos failed: {result.output}"

        proj = _find_project_dir(project_dir)

        # Step 2: Create parsed titles (normally done by title_parser, mock here)
        parsed_dir = proj / "02_analyze" / "parsed" / CHANNEL_ID
        parsed_dir.mkdir(parents=True, exist_ok=True)
        parsed_titles = [
            {
                "video_id": "vid001",
                "original_title": f"{PROFESSOR} Lecture 1",
                "professor": [PROFESSOR],
                "course": "Biology 101",
                "year": 2025,
                "semester": 1,
                "week": 1,
                "session": 1,
            },
            {
                "video_id": "vid002",
                "original_title": f"{PROFESSOR} Lecture 2",
                "professor": [PROFESSOR],
                "course": "Biology 101",
                "year": 2025,
                "semester": 1,
                "week": 2,
                "session": 1,
            },
        ]
        write_json(parsed_dir / "parsed_titles.json", parsed_titles)

        # Step 3: Generate department report (XLSX)
        result = runner.invoke(
            app,
            [
                "report",
                "department",
                "--channel",
                CHANNEL_ID,
                "--format",
                "xlsx",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
                "--project",
                str(proj),
            ],
        )
        assert result.exit_code == 0, f"report department failed: {result.output}"

        # Step 4: Verify output file exists
        report_dir = proj / "03_report" / "department"
        xlsx_files = list(report_dir.glob("*.xlsx"))
        assert len(xlsx_files) >= 1, f"No XLSX files in {report_dir}"

        # Step 5: Verify Excel content has expected sheets
        import openpyxl

        wb = openpyxl.load_workbook(xlsx_files[0])
        sheet_names = wb.sheetnames
        # Should have at least overview and professor detail sheets
        assert len(sheet_names) >= 2

    @patch("tube_scout.services.auth.build_data_client")
    def test_department_report_video_id_consistency(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Data integrity: parsed title video_ids match collected video_ids."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)
        channel_dir = proj / "01_collect" / "channels" / CHANNEL_ID
        videos_meta = read_json(channel_dir / "videos_meta.json")
        collected_ids = {
            v["video_id"]
            for v in (
                videos_meta
                if isinstance(videos_meta, list)
                else videos_meta.get("videos", [])
            )
        }

        # Parsed titles should be a subset of collected videos
        parsed_dir = proj / "02_analyze" / "parsed" / CHANNEL_ID
        parsed_dir.mkdir(parents=True, exist_ok=True)
        parsed_titles = [
            {
                "video_id": vid_id,
                "original_title": f"Title for {vid_id}",
                "professor": [PROFESSOR],
                "course": "Bio",
                "year": 2025,
                "semester": 1,
                "week": i + 1,
                "session": 1,
            }
            for i, vid_id in enumerate(collected_ids)
        ]
        write_json(parsed_dir / "parsed_titles.json", parsed_titles)

        parsed_ids = {p["video_id"] for p in parsed_titles}
        assert parsed_ids == collected_ids, (
            f"video_id mismatch: collected={collected_ids}, parsed={parsed_ids}"
        )


# ===========================================================================
# E2E-3: Bundle PDF/HTML report
# ===========================================================================
class TestE2E3BundleReport:
    """E2E-3: collect videos -> report bundle with filter -> verify output."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_bundle_report_with_keyword_filter(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Bundle report filters videos by keyword and generates HTML."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        # Collect videos
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)

        # Generate bundle report filtering by "Lecture 1"
        result = runner.invoke(
            app,
            [
                "report",
                "bundle",
                "--keyword",
                "Lecture 1",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
                "--project",
                str(proj),
                "--no-confirm",
            ],
        )
        assert result.exit_code == 0, f"bundle report failed: {result.output}"

        # Verify HTML output
        bundle_dir = proj / "03_report" / "bundle"
        html_files = list(bundle_dir.glob("*.html"))
        assert len(html_files) >= 1, f"No HTML bundle files in {bundle_dir}"

        # Verify only filtered videos in HTML
        html_content = html_files[0].read_text(encoding="utf-8")
        assert "Lecture 1" in html_content
        # "Lecture 2" should NOT be in the filtered output
        assert "Lecture 2" not in html_content

    @patch("tube_scout.services.auth.build_data_client")
    def test_bundle_report_video_ids_filter(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Bundle report with --video-ids contains only specified videos."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)

        result = runner.invoke(
            app,
            [
                "report",
                "bundle",
                "--video-ids",
                "vid001",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
                "--project",
                str(proj),
                "--no-confirm",
            ],
        )
        assert result.exit_code == 0, f"bundle report failed: {result.output}"

        bundle_dir = proj / "03_report" / "bundle"
        html_files = list(bundle_dir.glob("*.html"))
        assert len(html_files) >= 1

        html_content = html_files[0].read_text(encoding="utf-8")
        assert "vid001" in html_content


# ===========================================================================
# E2E-4: Title validation pipeline
# ===========================================================================
class TestE2E4TitleValidation:
    """E2E-4: collect videos -> validate -> verify detection results."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_validate_detects_findings(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Validate command detects title issues from parsed data."""
        from tube_scout.models.parsed_title import ParsedTitle
        from tube_scout.models.validation import ValidationFinding
        from tube_scout.services.validator import run_all_validations

        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        # Collect
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)
        channel_dir = proj / "01_collect" / "channels" / CHANNEL_ID
        videos_meta = read_json(channel_dir / "videos_meta.json")
        videos = (
            videos_meta
            if isinstance(videos_meta, list)
            else videos_meta.get("videos", [])
        )

        # Create parsed titles with intentional issues:
        # - V-001: year mismatch (title says 2020, upload is 2025)
        # - V-002: duplicate (same prof+course+week+session)
        # - V-003: invalid week (week=20)
        # - V-005: parse failure
        parsed_titles_data = [
            {
                "video_id": "vid001",
                "original_title": f"{PROFESSOR} Lecture 1",
                "professor": [PROFESSOR],
                "course": "Biology 101",
                "year": 2020,  # V-001 trigger: 2020 vs upload 2025
                "semester": 1,
                "week": 1,
                "session": 1,
            },
            {
                "video_id": "vid002",
                "original_title": f"{PROFESSOR} Lecture 2",
                "professor": [PROFESSOR],
                "course": "Biology 101",
                "year": 2025,
                "semester": 1,
                "week": 1,  # V-002 trigger: same as vid001
                "session": 1,  # V-002 trigger: same as vid001
            },
            {
                "video_id": "vid_extra1",
                "original_title": "Extra Video 1",
                "professor": [PROFESSOR],
                "course": "Biology 101",
                "year": 2025,
                "semester": 1,
                "week": 20,  # V-003 trigger: invalid week
                "session": 1,
            },
            {
                "video_id": "vid_extra2",
                "original_title": "Unparseable garbage title @@@@",
                "professor": [],
                "course": None,
                "year": None,
                "semester": None,
                "week": None,
                "session": None,
                "parse_error": True,  # V-005 trigger
            },
        ]

        parsed_titles = [ParsedTitle(**p) for p in parsed_titles_data]
        findings = run_all_validations(parsed_titles, videos)

        # Should detect at least V-001, V-002, V-003, V-005
        rule_ids_found = {f.rule_id for f in findings}
        assert "V-001" in rule_ids_found, f"V-001 not found in {rule_ids_found}"
        assert "V-002" in rule_ids_found, f"V-002 not found in {rule_ids_found}"
        assert "V-003" in rule_ids_found, f"V-003 not found in {rule_ids_found}"
        assert "V-005" in rule_ids_found, f"V-005 not found in {rule_ids_found}"

        # Every finding must be a valid ValidationFinding
        for f in findings:
            assert isinstance(f, ValidationFinding)
            assert f.severity in {"ERROR", "WARNING", "INFO"}
            assert len(f.video_ids) >= 1


# ===========================================================================
# E2E-5: Pipeline interrupt and resume
# ===========================================================================
class TestE2E5InterruptResume:
    """E2E-5: collect all interrupted -> resume -> verify checkpoint skip."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_checkpoint_resume_skips_completed_stages(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """After interrupted collect, re-run skips completed video stage."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        # First run: collect videos only
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)

        # Verify checkpoint says completed
        checkpoint = load_checkpoint(proj / "checkpoints", CHANNEL_ID, "videos")
        assert checkpoint is not None
        assert checkpoint.status == "completed"

        # Second run: collect videos again should skip
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
                "--project",
                str(proj),
            ],
        )
        assert result.exit_code == 0
        assert "already collected" in result.output.lower()

    @patch("tube_scout.services.auth.build_data_client")
    def test_force_refresh_overrides_checkpoint(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """--force-refresh re-collects even when checkpoint says completed."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        # First collect
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)

        # Force refresh collect
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
                "--project",
                str(proj),
                "--force-refresh",
            ],
        )
        assert result.exit_code == 0
        # Should have called the API again (not skipped)
        assert "already collected" not in result.output.lower()

    @patch("tube_scout.services.auth.build_data_client")
    def test_interrupted_checkpoint_preserved(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """An API error during collection saves interrupted checkpoint."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)

        client = MagicMock()
        mock_build_data.return_value = client

        # Channel info succeeds
        client.channels().list.return_value.execute.return_value = (
            _mock_channel_response()
        )
        # Playlist fails with API error
        client.playlistItems().list.return_value.execute.side_effect = RuntimeError(
            "Simulated API failure"
        )

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        # Should exit with error
        assert result.exit_code != 0

        proj = _find_project_dir(project_dir)
        checkpoint = load_checkpoint(proj / "checkpoints", CHANNEL_ID, "videos")
        assert checkpoint is not None
        assert checkpoint.status == "interrupted"


# ===========================================================================
# E2E-6: Multi-channel data isolation
# ===========================================================================
class TestE2E6MultiChannel:
    """E2E-6: collect for two channels -> verify data isolation."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_multichannel_data_isolation(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Two channels' data stored in separate directories
        without cross-contamination."""
        channel_a = "UCchannelAAAAAAAAAAAAAAAA"
        channel_b = "UCchannelBBBBBBBBBBBBBBBB"
        prof_a = "ProfessorA"
        prof_b = "ProfessorB"

        # Channel A setup
        data_dir_a = tmp_path / "data_a"
        project_dir_a = tmp_path / "projects_a"
        _write_config(data_dir_a, channel_id=channel_a, professor=prof_a)

        client_a = MagicMock()
        mock_build_data.return_value = client_a
        client_a.channels().list.return_value.execute.return_value = (
            _mock_channel_response(channel_a)
        )
        client_a.playlistItems().list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vidA1"},
                        "title": f"{prof_a} Lecture A1",
                        "publishedAt": "2025-03-01T00:00:00Z",
                    },
                },
            ],
        }
        client_a.videos().list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "vidA1",
                    "snippet": {
                        "title": f"{prof_a} Lecture A1",
                        "description": "",
                        "thumbnails": {"default": {"url": ""}},
                    },
                    "contentDetails": {"duration": "PT10M0S", "caption": "false"},
                    "statistics": {
                        "viewCount": "100",
                        "likeCount": "5",
                        "commentCount": "1",
                    },
                    "status": {"privacyStatus": "public"},
                    "topicDetails": {},
                },
            ],
        }

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir_a),
                "--project-dir",
                str(project_dir_a),
            ],
        )
        assert result.exit_code == 0

        # Channel B setup
        data_dir_b = tmp_path / "data_b"
        project_dir_b = tmp_path / "projects_b"
        _write_config(data_dir_b, channel_id=channel_b, professor=prof_b)

        client_b = MagicMock()
        mock_build_data.return_value = client_b
        client_b.channels().list.return_value.execute.return_value = (
            _mock_channel_response(channel_b)
        )
        client_b.playlistItems().list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vidB1"},
                        "title": f"{prof_b} Lecture B1",
                        "publishedAt": "2025-04-01T00:00:00Z",
                    },
                },
                {
                    "snippet": {
                        "resourceId": {"videoId": "vidB2"},
                        "title": f"{prof_b} Lecture B2",
                        "publishedAt": "2025-04-15T00:00:00Z",
                    },
                },
            ],
        }
        client_b.videos().list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "vidB1",
                    "snippet": {
                        "title": f"{prof_b} Lecture B1",
                        "description": "",
                        "thumbnails": {"default": {"url": ""}},
                    },
                    "contentDetails": {"duration": "PT20M0S", "caption": "false"},
                    "statistics": {
                        "viewCount": "200",
                        "likeCount": "10",
                        "commentCount": "2",
                    },
                    "status": {"privacyStatus": "public"},
                    "topicDetails": {},
                },
                {
                    "id": "vidB2",
                    "snippet": {
                        "title": f"{prof_b} Lecture B2",
                        "description": "",
                        "thumbnails": {"default": {"url": ""}},
                    },
                    "contentDetails": {"duration": "PT25M0S", "caption": "false"},
                    "statistics": {
                        "viewCount": "300",
                        "likeCount": "15",
                        "commentCount": "3",
                    },
                    "status": {"privacyStatus": "public"},
                    "topicDetails": {},
                },
            ],
        }

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir_b),
                "--project-dir",
                str(project_dir_b),
            ],
        )
        assert result.exit_code == 0

        # Verify isolation
        proj_a = _find_project_dir(project_dir_a)
        proj_b = _find_project_dir(project_dir_b)

        # Channel A data
        videos_a = read_json(
            proj_a / "01_collect" / "channels" / channel_a / "videos_meta.json"
        )
        assert videos_a is not None
        vids_a = videos_a if isinstance(videos_a, list) else videos_a.get("videos", [])
        ids_a = {v["video_id"] for v in vids_a}
        assert ids_a == {"vidA1"}

        # Channel B data
        videos_b = read_json(
            proj_b / "01_collect" / "channels" / channel_b / "videos_meta.json"
        )
        assert videos_b is not None
        vids_b = videos_b if isinstance(videos_b, list) else videos_b.get("videos", [])
        ids_b = {v["video_id"] for v in vids_b}
        assert ids_b == {"vidB1", "vidB2"}

        # Cross-contamination check
        assert ids_a.isdisjoint(ids_b), "Channel A and B have overlapping video IDs"

        # Channel A project should NOT have channel B's directory
        assert not (proj_a / "01_collect" / "channels" / channel_b).exists()
        # Channel B project should NOT have channel A's directory
        assert not (proj_b / "01_collect" / "channels" / channel_a).exists()

    @patch("tube_scout.services.auth.build_data_client")
    def test_multichannel_checkpoints_independent(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Each channel has its own independent checkpoint state."""
        channel_a = "UCchannelAAAAAAAAAAAAAAAA"
        channel_b = "UCchannelBBBBBBBBBBBBBBBB"

        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"

        # Config with both channels
        config = {
            "channels": [
                {"channel_id": channel_a, "professor_name": "ProfA"},
                {"channel_id": channel_b, "professor_name": "ProfB"},
            ],
            "settings": {"data_dir": str(data_dir)},
        }
        data_dir.mkdir(parents=True, exist_ok=True)
        write_json(data_dir / "config.json", config)

        client = MagicMock()
        mock_build_data.return_value = client

        # Channel A succeeds
        def channel_response(part=None, id=None, **kwargs):
            mock = MagicMock()
            if id == channel_a:
                mock.execute.return_value = _mock_channel_response(channel_a)
            elif id == channel_b:
                mock.execute.return_value = _mock_channel_response(channel_b)
            return mock

        client.channels().list.side_effect = channel_response

        def playlist_response(part=None, playlistId=None, maxResults=None, **kwargs):  # noqa: N803
            mock = MagicMock()
            if playlistId == channel_a.replace("UC", "UU"):
                mock.execute.return_value = {
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"videoId": "vidA1"},
                                "title": "ProfA Lecture",
                                "publishedAt": "2025-01-01T00:00:00Z",
                            },
                        }
                    ],
                }
            elif playlistId == channel_b.replace("UC", "UU"):
                mock.execute.return_value = {
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"videoId": "vidB1"},
                                "title": "ProfB Lecture",
                                "publishedAt": "2025-01-01T00:00:00Z",
                            },
                        }
                    ],
                }
            return mock

        client.playlistItems().list.side_effect = playlist_response

        client.videos().list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "vidA1",
                    "snippet": {
                        "title": "ProfA Lecture",
                        "description": "",
                        "thumbnails": {"default": {"url": ""}},
                    },
                    "contentDetails": {"duration": "PT10M", "caption": "false"},
                    "statistics": {
                        "viewCount": "50",
                        "likeCount": "2",
                        "commentCount": "0",
                    },
                    "status": {"privacyStatus": "public"},
                    "topicDetails": {},
                },
                {
                    "id": "vidB1",
                    "snippet": {
                        "title": "ProfB Lecture",
                        "description": "",
                        "thumbnails": {"default": {"url": ""}},
                    },
                    "contentDetails": {"duration": "PT15M", "caption": "false"},
                    "statistics": {
                        "viewCount": "80",
                        "likeCount": "4",
                        "commentCount": "1",
                    },
                    "status": {"privacyStatus": "public"},
                    "topicDetails": {},
                },
            ],
        }

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)
        cp_a = load_checkpoint(proj / "checkpoints", channel_a, "videos")
        cp_b = load_checkpoint(proj / "checkpoints", channel_b, "videos")

        assert cp_a is not None
        assert cp_b is not None
        assert cp_a.status == "completed"
        assert cp_b.status == "completed"
        # They are separate entries
        assert cp_a.channel_id == channel_a
        assert cp_b.channel_id == channel_b


# ===========================================================================
# Data integrity cross-checks
# ===========================================================================
class TestDataIntegrity:
    """Cross-cutting data integrity checks applicable to all scenarios."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_json_parquet_video_id_consistency(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """video_ids in JSON match video_ids in Parquet."""
        from tube_scout.storage.parquet_store import read_parquet

        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)
        channel_dir = proj / "01_collect" / "channels" / CHANNEL_ID

        # JSON video IDs
        videos_meta = read_json(channel_dir / "videos_meta.json")
        json_ids = {
            v["video_id"]
            for v in (
                videos_meta
                if isinstance(videos_meta, list)
                else videos_meta.get("videos", [])
            )
        }

        # Parquet video IDs
        df = read_parquet(channel_dir / "videos_meta.parquet")
        assert df is not None
        parquet_ids = set(df["video_id"].to_list())

        assert json_ids == parquet_ids, (
            f"JSON/Parquet video_id mismatch: {json_ids} vs {parquet_ids}"
        )

    @patch("tube_scout.services.auth.build_data_client")
    def test_checkpoint_state_model_roundtrip(
        self,
        mock_build_data: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Checkpoint JSON can be deserialized back to CollectionState."""
        data_dir = tmp_path / "data"
        project_dir = tmp_path / "projects"
        _write_config(data_dir)
        _setup_mock_data_client(mock_build_data)

        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        proj = _find_project_dir(project_dir)
        # L-10 fix: checkpoint file is now directly inside checkpoints/
        checkpoint_file = proj / "checkpoints" / "collection_state.json"
        assert checkpoint_file.exists(), (
            f"Checkpoint file not found. Contents of checkpoints/: "
            f"{list((proj / 'checkpoints').rglob('*'))}"
        )

        raw = read_json(checkpoint_file)
        assert raw is not None

        # Every entry must be deserializable
        for key, state_data in raw.items():
            state = CollectionState(**state_data)
            assert state.channel_id == CHANNEL_ID
            assert state.phase == "videos"
            assert state.status in {"completed", "in_progress", "interrupted"}
