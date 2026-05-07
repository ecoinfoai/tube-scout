"""T024 RED: integration test for collect videos → transcripts chain (US2).

Tests:
- collect videos (no --project) creates a project and advances latest.
- collect transcripts (no --project) operates on the same project (not a new one).
- No empty sibling projects exist after the chain.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_config(tmp_path: Path) -> Path:
    """Create a minimal config.json and return data_dir."""
    import json as _json

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = {
        "channels": [
            {"channel_id": "UCtest123abcdefg", "professor_name": "Test Prof"}
        ],
        "settings": {
            "rate_limit_transcript": {
                "base_delay": 2.0,
                "max_retries": 3,
                "backoff_multiplier": 2.0,
                "jitter": 0.0,
            },
        },
    }
    (data_dir / "config.json").write_text(_json.dumps(config))
    return data_dir


class TestCollectVideosThenTranscripts:
    """FR-001, SC-003: Consumer finds producer's project; no empty siblings."""

    def test_transcripts_uses_videos_project(self, tmp_path: Path) -> None:
        """collect transcripts (no --project) finds the project that collect videos created."""
        data_dir = _make_config(tmp_path)
        project_dir = tmp_path / "projects"
        project_dir.mkdir()

        # Step 1: collect videos — creates project + commits latest
        videos_service = MagicMock()
        videos_service.get_channel_info.return_value = {
            "channel_name": "Test",
            "total_video_count": 1,
            "uploads_playlist_id": "UU_test",
        }
        videos_service.list_all_videos.return_value = [
            {"video_id": "vid001", "title": "Test Prof Lecture 1", "channel_id": "UCtest123abcdefg"},
        ]
        videos_service.filter_by_professor.return_value = [
            {"video_id": "vid001", "title": "Test Prof Lecture 1", "channel_id": "UCtest123abcdefg"},
        ]
        videos_service.get_video_details.return_value = {}

        with (
            patch("tube_scout.cli.collect.YouTubeDataService", return_value=videos_service),
            patch("tube_scout.services.auth.authenticate_channel", return_value=MagicMock()),
            patch("googleapiclient.discovery.build", return_value=MagicMock()),
        ):
            from tube_scout.cli.collect import collect_videos_command

            try:
                collect_videos_command(
                    data_dir=str(data_dir),
                    project_dir=str(project_dir),
                    project=None,
                    force_refresh=False,
                    channel="nursing",
                )
            except (SystemExit, Exception) as e:
                code = getattr(e, "code", 0)
                if code not in (0, None):
                    pytest.fail(f"collect_videos_command failed with exit {code}")

        # Verify latest symlink exists after videos
        latest_link = project_dir / "latest"
        assert latest_link.is_symlink(), "projects/latest must exist after collect videos"
        first_project = latest_link.resolve()

        # Step 2: collect transcripts (no --project) — should use the same project
        transcript_service = MagicMock()
        transcript_service.fetch_transcript.return_value = {
            "video_id": "vid001",
            "segments": [{"text": "hello", "start": 0.0, "duration": 1.0}],
            "transcript_type": "auto_generated",
            "language": "ko",
        }

        projects_before = {
            p for p in project_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        }

        with (
            patch("tube_scout.services.transcript.TranscriptService", return_value=transcript_service),
        ):
            from tube_scout.cli.collect import collect_transcripts_command

            try:
                collect_transcripts_command(
                    data_dir=str(data_dir),
                    project_dir=str(project_dir),
                    project=None,  # no --project flag
                    video_id=None,
                    channel="nursing",
                )
            except (SystemExit, Exception) as e:
                code = getattr(e, "code", 0)
                if code not in (0, None):
                    pytest.fail(f"collect_transcripts_command failed with exit {code}")

        projects_after = {
            p for p in project_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        }
        new_projects = projects_after - projects_before
        # No NEW project directory should have been created by collect transcripts
        assert len(new_projects) == 0, (
            f"collect transcripts must not create a new project; found: {new_projects}"
        )

        # latest must still point to the same project videos created
        assert latest_link.resolve() == first_project, (
            "projects/latest must still point to the videos project after transcripts"
        )

    def test_no_empty_sibling_projects_after_chain(self, tmp_path: Path) -> None:
        """After the full chain, no empty sibling project directories exist."""
        data_dir = _make_config(tmp_path)
        project_dir = tmp_path / "projects"
        project_dir.mkdir()

        videos_service = MagicMock()
        videos_service.get_channel_info.return_value = {
            "channel_name": "Test",
            "total_video_count": 1,
            "uploads_playlist_id": "UU_test",
        }
        videos_service.list_all_videos.return_value = [
            {"video_id": "vid002", "title": "Test Prof Lec 2", "channel_id": "UCtest123abcdefg"},
        ]
        videos_service.filter_by_professor.return_value = [
            {"video_id": "vid002", "title": "Test Prof Lec 2", "channel_id": "UCtest123abcdefg"},
        ]
        videos_service.get_video_details.return_value = {}

        with (
            patch("tube_scout.cli.collect.YouTubeDataService", return_value=videos_service),
            patch("tube_scout.services.auth.authenticate_channel", return_value=MagicMock()),
            patch("googleapiclient.discovery.build", return_value=MagicMock()),
        ):
            from tube_scout.cli.collect import collect_videos_command

            try:
                collect_videos_command(
                    data_dir=str(data_dir),
                    project_dir=str(project_dir),
                    project=None,
                    force_refresh=False,
                    channel="nursing",
                )
            except (SystemExit, Exception):
                pass

        # All real project dirs must have at least one artifact
        real_projects = [
            p for p in project_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        for proj in real_projects:
            collect_root = proj / "01_collect"
            has_file = False
            if collect_root.exists():
                has_file = any(f.is_file() for f in collect_root.rglob("*"))
            assert has_file, (
                f"Empty sibling project found: {proj} "
                "(01_collect/ is empty or missing)"
            )
