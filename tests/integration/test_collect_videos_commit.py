"""T023 RED: integration tests for collect_videos_command commit_latest behavior (US2).

Tests:
- Success path: commit_latest() called exactly once after data write completes.
- Exception path: commit_latest() NOT called when exception is raised mid-run.
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


def _make_config(tmp_path: Path) -> Path:
    """Create a minimal config.json and return data_dir."""
    import json

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
    (data_dir / "config.json").write_text(json.dumps(config))
    return data_dir


class TestCollectVideosCommitLatest:
    """commit_latest() must be called on success, never on exception."""

    def test_commit_latest_called_on_success(self, tmp_path: Path) -> None:
        """When collect_videos_command succeeds, commit_latest() is called once."""
        data_dir = _make_config(tmp_path)
        project_dir = tmp_path / "projects"
        project_dir.mkdir()

        mock_service = MagicMock()
        mock_service.get_channel_info.return_value = {
            "channel_name": "Test",
            "total_video_count": 1,
            "uploads_playlist_id": "UU_test",
        }
        mock_service.list_all_videos.return_value = [
            {"video_id": "vid001", "title": "Test Prof Lecture 1", "channel_id": "UCtest123abcdefg"},
        ]
        mock_service.filter_by_professor.return_value = [
            {"video_id": "vid001", "title": "Test Prof Lecture 1", "channel_id": "UCtest123abcdefg"},
        ]
        mock_service.get_video_details.return_value = {}

        commit_latest_calls: list = []

        def fake_commit_latest() -> None:
            commit_latest_calls.append(1)

        with (
            patch(
                "tube_scout.cli.collect.YouTubeDataService",
                return_value=mock_service,
            ),
            patch(
                "tube_scout.services.auth.authenticate_channel",
                return_value=MagicMock(),
            ),
            patch("googleapiclient.discovery.build", return_value=MagicMock()),
            patch(
                "tube_scout.cli.collect.resolve_project"
            ) as mock_resolve,
        ):
            # Make resolve_project return a manager where commit_latest is tracked
            from tube_scout.output.manager import ProjectManager

            real_mgr = ProjectManager(projects_root=project_dir)
            real_mgr.create_project()
            real_mgr.commit_latest = fake_commit_latest  # type: ignore[method-assign]
            mock_resolve.return_value = real_mgr

            from tube_scout.cli.collect import collect_videos_command

            try:
                collect_videos_command(
                    data_dir=str(data_dir),
                    project_dir=str(project_dir),
                    project=None,
                    force_refresh=False,
                    channel="nursing",
                )
            except SystemExit:
                pass  # allow non-zero exits, we just check commit_latest

        assert len(commit_latest_calls) == 1, (
            "commit_latest() must be called exactly once on success"
        )

    def test_commit_latest_not_called_on_exception(self, tmp_path: Path) -> None:
        """When an exception is raised mid-run, commit_latest() is NOT called."""
        data_dir = _make_config(tmp_path)
        project_dir = tmp_path / "projects"
        project_dir.mkdir()

        commit_latest_calls: list = []

        def fake_commit_latest() -> None:
            commit_latest_calls.append(1)

        mock_service = MagicMock()
        mock_service.get_channel_info.side_effect = RuntimeError("network error")

        with (
            patch(
                "tube_scout.cli.collect.YouTubeDataService",
                return_value=mock_service,
            ),
            patch(
                "tube_scout.services.auth.authenticate_channel",
                return_value=MagicMock(),
            ),
            patch("googleapiclient.discovery.build", return_value=MagicMock()),
            patch(
                "tube_scout.cli.collect.resolve_project"
            ) as mock_resolve,
        ):
            from tube_scout.output.manager import ProjectManager

            real_mgr = ProjectManager(projects_root=project_dir)
            real_mgr.create_project()
            real_mgr.commit_latest = fake_commit_latest  # type: ignore[method-assign]
            mock_resolve.return_value = real_mgr

            import typer

            from tube_scout.cli.collect import collect_videos_command

            with pytest.raises((typer.Exit, SystemExit)):
                collect_videos_command(
                    data_dir=str(data_dir),
                    project_dir=str(project_dir),
                    project=None,
                    force_refresh=False,
                    channel="nursing",
                )

        assert len(commit_latest_calls) == 0, (
            "commit_latest() must NOT be called when an exception occurs"
        )
