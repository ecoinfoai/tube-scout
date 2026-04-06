"""Tests for collect_all_command with --channel, error handling, and resume."""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestCollectAllChannel:
    """Tests for collect_all --channel param (T023)."""

    @patch("tube_scout.cli.collect.collect_analytics_command")
    @patch("tube_scout.cli.collect.collect_retention_command")
    @patch("tube_scout.cli.collect.collect_transcripts_command")
    @patch("tube_scout.cli.collect.collect_comments_command")
    @patch("tube_scout.cli.collect.collect_videos_command")
    @patch("tube_scout.cli.collect.resolve_project")
    def test_channel_param_passed_to_stages(
        self,
        mock_resolve: MagicMock,
        mock_videos: MagicMock,
        mock_comments: MagicMock,
        mock_transcripts: MagicMock,
        mock_retention: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        """When --channel is provided, pass to stages."""
        from tube_scout.cli.collect import collect_all_command

        mock_mgr = MagicMock()
        mock_mgr.project_dir = Path("/tmp/test-project")
        mock_resolve.return_value = mock_mgr

        collect_all_command(
            data_dir="./data",
            project_dir="./projects",
            project=None,
            force_refresh=False,
            channel="간호학과",
        )

        # Videos should be called with channel param
        mock_videos.assert_called_once()
        call_kwargs = mock_videos.call_args
        assert call_kwargs.kwargs.get("channel") == "간호학과" or (
            len(call_kwargs.args) > 0 and "간호학과" in str(call_kwargs)
        )

    @patch("tube_scout.cli.collect.collect_analytics_command")
    @patch("tube_scout.cli.collect.collect_retention_command")
    @patch("tube_scout.cli.collect.collect_transcripts_command")
    @patch("tube_scout.cli.collect.collect_comments_command")
    @patch("tube_scout.cli.collect.collect_videos_command")
    @patch("tube_scout.cli.collect.resolve_project")
    def test_all_five_stages_invoked(
        self,
        mock_resolve: MagicMock,
        mock_videos: MagicMock,
        mock_comments: MagicMock,
        mock_transcripts: MagicMock,
        mock_retention: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        """All 5 collection stages should be invoked."""
        from tube_scout.cli.collect import collect_all_command

        mock_mgr = MagicMock()
        mock_mgr.project_dir = Path("/tmp/test-project")
        mock_resolve.return_value = mock_mgr

        collect_all_command(
            data_dir="./data",
            project_dir="./projects",
            project=None,
            force_refresh=False,
            channel=None,
        )

        mock_videos.assert_called_once()
        mock_comments.assert_called_once()
        mock_transcripts.assert_called_once()
        mock_retention.assert_called_once()
        mock_analytics.assert_called_once()


class TestCollectAllErrorHandling:
    """Tests for pipeline error handling (T024)."""

    @patch("tube_scout.cli.collect.collect_analytics_command")
    @patch("tube_scout.cli.collect.collect_retention_command")
    @patch("tube_scout.cli.collect.collect_transcripts_command")
    @patch("tube_scout.cli.collect.collect_comments_command")
    @patch("tube_scout.cli.collect.collect_videos_command")
    @patch("tube_scout.cli.collect.resolve_project")
    def test_video_failure_aborts_pipeline(
        self,
        mock_resolve: MagicMock,
        mock_videos: MagicMock,
        mock_comments: MagicMock,
        mock_transcripts: MagicMock,
        mock_retention: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        """If video listing (stage 1) fails, pipeline should abort."""
        from tube_scout.cli.collect import collect_all_command

        mock_mgr = MagicMock()
        mock_mgr.project_dir = Path("/tmp/test-project")
        mock_resolve.return_value = mock_mgr
        mock_videos.side_effect = Exception("API quota exceeded")

        collect_all_command(
            data_dir="./data",
            project_dir="./projects",
            project=None,
            force_refresh=False,
            channel=None,
        )

        # Subsequent stages should NOT be called
        mock_comments.assert_not_called()
        mock_transcripts.assert_not_called()

    @patch("tube_scout.cli.collect.collect_analytics_command")
    @patch("tube_scout.cli.collect.collect_retention_command")
    @patch("tube_scout.cli.collect.collect_transcripts_command")
    @patch("tube_scout.cli.collect.collect_comments_command")
    @patch("tube_scout.cli.collect.collect_videos_command")
    @patch("tube_scout.cli.collect.resolve_project")
    def test_non_video_failure_continues_pipeline(
        self,
        mock_resolve: MagicMock,
        mock_videos: MagicMock,
        mock_comments: MagicMock,
        mock_transcripts: MagicMock,
        mock_retention: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        """If a non-video stage fails, pipeline should continue."""
        from tube_scout.cli.collect import collect_all_command

        mock_mgr = MagicMock()
        mock_mgr.project_dir = Path("/tmp/test-project")
        mock_resolve.return_value = mock_mgr
        mock_comments.side_effect = Exception("Comments error")

        collect_all_command(
            data_dir="./data",
            project_dir="./projects",
            project=None,
            force_refresh=False,
            channel=None,
        )

        # Videos ran, comments failed, but transcripts+ should still run
        mock_videos.assert_called_once()
        mock_transcripts.assert_called_once()
        mock_retention.assert_called_once()
        mock_analytics.assert_called_once()


class TestStageCompletion:
    """Tests for is_stage_complete() and mark_stage_complete() (T025)."""

    def test_mark_and_check_stage_complete(self, tmp_path: Path) -> None:
        """mark_stage_complete should make is_stage_complete return True."""
        from tube_scout.storage.checkpoint import (
            is_stage_complete,
            mark_stage_complete,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        assert not is_stage_complete(checkpoint_dir, "UCtest", "videos")
        mark_stage_complete(checkpoint_dir, "UCtest", "videos")
        assert is_stage_complete(checkpoint_dir, "UCtest", "videos")

    def test_different_stages_independent(self, tmp_path: Path) -> None:
        """Completing one stage should not affect others."""
        from tube_scout.storage.checkpoint import (
            is_stage_complete,
            mark_stage_complete,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        mark_stage_complete(checkpoint_dir, "UCtest", "videos")
        assert is_stage_complete(checkpoint_dir, "UCtest", "videos")
        assert not is_stage_complete(checkpoint_dir, "UCtest", "transcripts")

    def test_different_channels_independent(self, tmp_path: Path) -> None:
        """Completing a stage for one channel should not affect others."""
        from tube_scout.storage.checkpoint import (
            is_stage_complete,
            mark_stage_complete,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        mark_stage_complete(checkpoint_dir, "UCchan1", "videos")
        assert not is_stage_complete(checkpoint_dir, "UCchan2", "videos")
