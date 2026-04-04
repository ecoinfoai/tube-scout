"""Adversary tests for pipeline edge cases (T038)."""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestForceRefreshOverride:
    """Test --force-refresh behavior in pipeline."""

    @patch("tube_scout.cli.collect.collect_analytics_command")
    @patch("tube_scout.cli.collect.collect_retention_command")
    @patch("tube_scout.cli.collect.collect_transcripts_command")
    @patch("tube_scout.cli.collect.collect_comments_command")
    @patch("tube_scout.cli.collect.collect_videos_command")
    @patch("tube_scout.cli.collect.resolve_project")
    def test_force_refresh_passed_to_videos(
        self,
        mock_resolve: MagicMock,
        mock_videos: MagicMock,
        mock_comments: MagicMock,
        mock_transcripts: MagicMock,
        mock_retention: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        """--force-refresh should be passed to the videos stage."""
        from tube_scout.cli.collect import collect_all_command

        mock_mgr = MagicMock()
        mock_mgr.project_dir = Path("/tmp/test")
        mock_resolve.return_value = mock_mgr

        collect_all_command(
            data_dir="./data",
            project_dir="./projects",
            project=None,
            force_refresh=True,
            channel=None,
        )

        call_kwargs = mock_videos.call_args.kwargs
        assert call_kwargs.get("force_refresh") is True


class TestPipelineMultipleFailures:
    """Test pipeline behavior with multiple stage failures."""

    @patch("tube_scout.cli.collect.collect_analytics_command")
    @patch("tube_scout.cli.collect.collect_retention_command")
    @patch("tube_scout.cli.collect.collect_transcripts_command")
    @patch("tube_scout.cli.collect.collect_comments_command")
    @patch("tube_scout.cli.collect.collect_videos_command")
    @patch("tube_scout.cli.collect.resolve_project")
    def test_multiple_non_video_failures_all_continue(
        self,
        mock_resolve: MagicMock,
        mock_videos: MagicMock,
        mock_comments: MagicMock,
        mock_transcripts: MagicMock,
        mock_retention: MagicMock,
        mock_analytics: MagicMock,
    ) -> None:
        """Multiple non-video stage failures should not stop the pipeline."""
        from tube_scout.cli.collect import collect_all_command

        mock_mgr = MagicMock()
        mock_mgr.project_dir = Path("/tmp/test")
        mock_resolve.return_value = mock_mgr

        mock_comments.side_effect = Exception("Comments error")
        mock_transcripts.side_effect = Exception("Transcript error")
        mock_retention.side_effect = Exception("Retention error")

        collect_all_command(
            data_dir="./data",
            project_dir="./projects",
            project=None,
            force_refresh=False,
            channel=None,
        )

        # Videos and analytics should still be called
        mock_videos.assert_called_once()
        mock_analytics.assert_called_once()


class TestStageCompletionEdgeCases:
    """Edge cases for stage completion tracking."""

    def test_mark_complete_twice_idempotent(self, tmp_path: Path) -> None:
        """Marking a stage complete twice should not error."""
        from tube_scout.storage.checkpoint import (
            is_stage_complete,
            mark_stage_complete,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        mark_stage_complete(checkpoint_dir, "UCtest", "videos")
        mark_stage_complete(checkpoint_dir, "UCtest", "videos")
        assert is_stage_complete(checkpoint_dir, "UCtest", "videos")

    def test_empty_checkpoint_dir(self, tmp_path: Path) -> None:
        """Checking stage completion on empty dir should return False."""
        from tube_scout.storage.checkpoint import is_stage_complete

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        assert not is_stage_complete(checkpoint_dir, "UCtest", "videos")
