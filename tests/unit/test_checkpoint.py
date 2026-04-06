"""Tests for checkpoint manager."""

import json
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


class TestAnalyticsIncrementalTracking:
    """Tests for incremental analytics date tracking (T016)."""

    def test_save_analytics_last_dates(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            status="completed",
            analytics_last_dates={
                "daily_metrics": "2024-03-01",
                "traffic_sources": "2024-03-01",
            },
        )
        save_checkpoint(tmp_data_dir, state)
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics")
        assert loaded is not None
        assert loaded.analytics_last_dates["daily_metrics"] == "2024-03-01"
        assert loaded.analytics_last_dates["traffic_sources"] == "2024-03-01"

    def test_update_analytics_last_dates(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            status="completed",
            analytics_last_dates={"daily_metrics": "2024-01-01"},
        )
        save_checkpoint(tmp_data_dir, state)

        # Update with new date
        state.analytics_last_dates["daily_metrics"] = "2024-03-15"
        state.analytics_last_dates["geography"] = "2024-03-15"
        save_checkpoint(tmp_data_dir, state)

        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics")
        assert loaded.analytics_last_dates["daily_metrics"] == "2024-03-15"
        assert loaded.analytics_last_dates["geography"] == "2024-03-15"

    def test_empty_analytics_last_dates_on_first_run(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            status="in_progress",
        )
        save_checkpoint(tmp_data_dir, state)
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics")
        assert loaded.analytics_last_dates == {}

    def test_analytics_phase_independent_from_videos(self, tmp_data_dir: Path) -> None:
        state_v = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            status="completed",
        )
        state_a = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            status="completed",
            analytics_last_dates={"daily_metrics": "2024-03-01"},
        )
        save_checkpoint(tmp_data_dir, state_v)
        save_checkpoint(tmp_data_dir, state_a)

        loaded_v = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        loaded_a = load_checkpoint(
            tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics"
        )
        assert loaded_v.analytics_last_dates == {}
        assert loaded_a.analytics_last_dates["daily_metrics"] == "2024-03-01"

    def test_clear_analytics_checkpoint(self, tmp_data_dir: Path) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            status="completed",
            analytics_last_dates={"daily_metrics": "2024-03-01"},
        )
        save_checkpoint(tmp_data_dir, state)
        clear_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics")
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "analytics")
        assert loaded is None


class TestCheckpointCorruptionRecovery:
    """Tests for H-04: corrupted JSON recovery, H-05: schema validation failure."""

    def test_load_corrupt_json_returns_none(self, tmp_data_dir: Path) -> None:
        """Corrupted JSON file should return None (not raise)."""
        # Write corrupt file at the path _checkpoint_path resolves to
        cp_file = tmp_data_dir / "collection_state.json"
        cp_file.write_text("{invalid json content!!!", encoding="utf-8")

        result = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert result is None

    def test_load_invalid_schema_returns_none(self, tmp_data_dir: Path) -> None:
        """JSON with invalid schema should return None and create .bak."""
        cp_file = tmp_data_dir / "collection_state.json"
        # Valid JSON but missing required fields for CollectionState
        bad_data = {
            "UCxxxxxxxxxxxxxxxxxxxxxx:videos": {
                "not_a_valid_field": True,
            }
        }
        cp_file.write_text(json.dumps(bad_data), encoding="utf-8")

        result = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert result is None
        # .bak file should be created
        assert (tmp_data_dir / "collection_state.json.bak").exists()

    def test_save_after_corrupt_load_works(self, tmp_data_dir: Path) -> None:
        """After loading corrupt file returns None, saving new state should work."""
        cp_file = tmp_data_dir / "collection_state.json"
        cp_file.write_text("NOT JSON", encoding="utf-8")

        # Load returns None due to corruption
        result = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert result is None

        # Save new state should succeed
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
            status="in_progress",
        )
        save_checkpoint(tmp_data_dir, state)
        loaded = load_checkpoint(tmp_data_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is not None
        assert loaded.status == "in_progress"

    def test_migrates_old_double_nested_path(self, tmp_path: Path) -> None:
        """Files at old checkpoints/checkpoints/ path should be auto-migrated."""
        checkpoint_dir = tmp_path / "checkpoints"
        old_nested = checkpoint_dir / "checkpoints"
        old_nested.mkdir(parents=True)
        old_file = old_nested / "collection_state.json"
        state_data = {
            "UCxxxxxxxxxxxxxxxxxxxxxx:videos": {
                "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                "phase": "videos",
                "status": "completed",
            }
        }
        old_file.write_text(json.dumps(state_data), encoding="utf-8")

        loaded = load_checkpoint(checkpoint_dir, "UCxxxxxxxxxxxxxxxxxxxxxx", "videos")
        assert loaded is not None
        assert loaded.status == "completed"
        # File should now be at the new path
        assert (checkpoint_dir / "collection_state.json").exists()
        # Old nested file should be gone
        assert not old_file.exists()
