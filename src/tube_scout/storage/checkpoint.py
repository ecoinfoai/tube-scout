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
