"""Checkpoint manager for collection resume support."""

import json
import logging
import shutil
from pathlib import Path

from pydantic import ValidationError

from tube_scout.models.config import CollectionState
from tube_scout.storage.json_store import read_json, write_json

logger = logging.getLogger(__name__)


def _checkpoint_path(data_dir: Path) -> Path:
    """Return the path to the checkpoint state file.

    Args:
        data_dir: Checkpoint directory (e.g., project/checkpoints/).

    Returns:
        Path to collection_state.json inside data_dir.
    """
    new_path = data_dir / "collection_state.json"
    # Migrate from old double-nested path if it exists
    old_path = data_dir / "checkpoints" / "collection_state.json"
    if not new_path.exists() and old_path.exists():
        logger.info("Migrating checkpoint from %s to %s", old_path, new_path)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
        # Clean up empty old directory
        try:
            old_path.parent.rmdir()
        except OSError:
            pass
    return new_path


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
    try:
        all_states = read_json(filepath) or {}
    except json.JSONDecodeError:
        logger.warning("Corrupt checkpoint JSON at %s; overwriting.", filepath)
        all_states = {}
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
    try:
        all_states = read_json(filepath)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("Corrupt checkpoint JSON at %s; starting fresh.", filepath)
        return None
    if all_states is None:
        return None
    key = _state_key(channel_id, phase)
    state_data = all_states.get(key)
    if state_data is None:
        return None
    try:
        return CollectionState(**state_data)
    except ValidationError:
        logger.warning(
            "Checkpoint schema validation failed at %s; "
            "backing up to .bak and starting fresh.",
            filepath,
        )
        bak_path = filepath.with_suffix(".json.bak")
        shutil.copy2(filepath, bak_path)
        return None


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
    try:
        all_states = read_json(filepath)
    except json.JSONDecodeError:
        logger.warning("Corrupt checkpoint JSON at %s; nothing to clear.", filepath)
        return
    if all_states is None:
        return
    key = _state_key(channel_id, phase)
    all_states.pop(key, None)
    write_json(filepath, all_states)
