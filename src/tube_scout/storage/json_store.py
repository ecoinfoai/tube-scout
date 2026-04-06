"""JSON file read/write with atomic write support."""

import json
import tempfile
from pathlib import Path
from typing import Any


def read_json(filepath: Path) -> dict[str, Any] | None:
    """Read JSON data from file.

    Args:
        filepath: Path to the JSON file.

    Returns:
        Parsed JSON data as dict, or None if file does not exist.
    """
    if not filepath.exists():
        return None
    with open(filepath, encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(filepath: Path, data: Any) -> None:
    """Write data to JSON file atomically (temp file then rename).

    Args:
        filepath: Path to the output JSON file.
        data: Data to serialize as JSON.

    Raises:
        TypeError: If data is not JSON-serializable.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then rename for atomicity
    fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp", prefix=".json_")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        Path(tmp_path).replace(filepath)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
