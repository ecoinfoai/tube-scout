"""Tests for checkpoint manager."""

from pathlib import Path

from tube_scout.models.config import CollectionState
from tube_scout.storage.checkpoint import (
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


class TestCheckpointManager:
    """Tests for checkpoint save/load/clear operations."""

    def test_save_and_load_checkpoint(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            last_page_token="token123",
            total_expected=100,
            total_collected=50,
            status="in_progress",
        )
        save_checkpoint(tmp_data_dir, state)
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is not None
        assert loaded.channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert loaded.phase == "videos"
        assert loaded.last_page_token == "token123"
        assert loaded.total_collected == 50
        assert loaded.status == "in_progress"

    def test_load_nonexistent_returns_none(self, tmp_data_dir: Path) -> None:
        result = load_checkpoint(tmp_data_dir, "UCnonexistent", "videos")
        assert result is None

    def test_resume_detection(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            total_expected=100,
            total_collected=50,
            status="interrupted",
        )
        save_checkpoint(tmp_data_dir, state)
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is not None
        assert loaded.status == "interrupted"
        assert loaded.total_collected < loaded.total_expected

    def test_clear_checkpoint(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            total_expected=100,
            total_collected=50,
            status="in_progress",
        )
        save_checkpoint(tmp_data_dir, state)
        clear_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is None

    def test_force_refresh_clears(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="comments",
            total_expected=200,
            total_collected=100,
            status="in_progress",
        )
        save_checkpoint(tmp_data_dir, state)
        clear_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "comments")
        result = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "comments")
        assert result is None

    def test_multiple_phases_independent(self, tmp_data_dir: Path) -> None:
        state_videos = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            total_collected=10,
            status="completed",
        )
        state_comments = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="comments",
            total_collected=5,
            status="in_progress",
        )
        save_checkpoint(tmp_data_dir, state_videos)
        save_checkpoint(tmp_data_dir, state_comments)

        loaded_v = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        loaded_c = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "comments")
        assert loaded_v.status == "completed"
        assert loaded_c.status == "in_progress"
