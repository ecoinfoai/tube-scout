"""Checkpoint manager for collection resume support."""

from pathlib import Path

from tube_scout.models.config import CollectionState
from tube_scout.storage.json_store import read_json, write_json


def _checkpoint_path(data_dir: Path) -> Path:
    """Return the path to the checkpoint state file."""
    return data_dir / "checkpoints" / "collection_state.json"


def _state_key(channel_id: str, phase: str) -> str:
    """Return a unique key for a channel/phase combination."""
    return f"{channel_id}:{phase}"


def save_checkpoint(data_dir: Path, state: CollectionState) -> None:
    """Save a collection checkpoint state.

    Args:
        data_dir: Root data directory.
        state: CollectionState to save.
    """
    filepath = _checkpoint_path(data_dir)
    all_states = read_json(filepath) or {}
    key = _state_key(state.channel_id, state.phase)
    all_states[key] = state.model_dump(mode="json")
    write_json(filepath, all_states)


def load_checkpoint(
    data_dir: Path, channel_id: str, phase: str
) -> CollectionState | None:
    """Load a collection checkpoint state.

    Args:
        data_dir: Root data directory.
        channel_id: YouTube channel ID.
        phase: Collection phase name.

    Returns:
        CollectionState if found, None otherwise.
    """
    filepath = _checkpoint_path(data_dir)
    all_states = read_json(filepath)
    if all_states is None:
        return None
    key = _state_key(channel_id, phase)
    state_data = all_states.get(key)
    if state_data is None:
        return None
    return CollectionState(**state_data)


def is_stage_complete(data_dir: Path, channel_id: str, stage_name: str) -> bool:
    """Check if a pipeline stage is marked as complete.

    Args:
        data_dir: Root data directory (checkpoints dir).
        channel_id: YouTube channel ID.
        stage_name: Pipeline stage name.

    Returns:
        True if the stage is marked as complete.
    """
    state = load_checkpoint(data_dir, channel_id, stage_name)
    if state is None:
        return False
    return state.stage_completed


def mark_stage_complete(data_dir: Path, channel_id: str, stage_name: str) -> None:
    """Mark a pipeline stage as complete.

    Args:
        data_dir: Root data directory (checkpoints dir).
        channel_id: YouTube channel ID.
        stage_name: Pipeline stage name.
    """
    state = load_checkpoint(data_dir, channel_id, stage_name)
    if state is None:
        from datetime import UTC, datetime

        state = CollectionState(
            channel_id=channel_id,
            phase=stage_name,
            status="completed",
            stage_completed=True,
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    else:
        state.stage_completed = True
        state.status = "completed"
    save_checkpoint(data_dir, state)


def clear_checkpoint(data_dir: Path, channel_id: str, phase: str) -> None:
    """Clear a collection checkpoint (for force-refresh).

    Args:
        data_dir: Root data directory.
        channel_id: YouTube channel ID.
        phase: Collection phase name.
    """
    filepath = _checkpoint_path(data_dir)
    all_states = read_json(filepath)
    if all_states is None:
        return
    key = _state_key(channel_id, phase)
    all_states.pop(key, None)
    write_json(filepath, all_states)
