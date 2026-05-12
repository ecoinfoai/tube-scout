"""Contract tests — migrate_to_v4 signature and version guard (spec 013 T005)."""

from __future__ import annotations

import inspect
import sqlite3
import tempfile
from pathlib import Path

import pytest


def test_migrate_to_v4_signature_matches_contract() -> None:
    """migrate_to_v4 must exist in storage.content_db with (db_path: Path) -> None."""
    from tube_scout.storage import content_db

    assert hasattr(content_db, "migrate_to_v4"), (
        "migrate_to_v4 not found in tube_scout.storage.content_db — implement per spec 013"
    )
    fn = content_db.migrate_to_v4
    sig = inspect.signature(fn)
    params = list(sig.parameters)
    assert params == ["db_path"], (
        f"Expected parameters ['db_path'], got {params}"
    )
    ann = sig.parameters["db_path"].annotation
    assert ann is Path, (
        f"db_path annotation must be Path, got {ann}"
    )
    assert sig.return_annotation is None or sig.return_annotation == inspect.Parameter.empty or sig.return_annotation is type(None), (
        f"Return annotation must be None, got {sig.return_annotation}"
    )


def test_migrate_raises_when_version_below_3() -> None:
    """migrate_to_v4 must raise ValueError when PRAGMA user_version < 3."""
    from tube_scout.storage.content_db import migrate_to_v4

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA user_version = 2;")

        with pytest.raises(ValueError, match="user_version"):
            migrate_to_v4(db_path)
    finally:
        db_path.unlink(missing_ok=True)
