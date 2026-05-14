"""Cross-spec boundary integration tests (Constitution VII).

Originally introduced as T045 for the predecessor media-adapter spec
(B-X1-1 through B-X1-9). Spec 013 Phase 5 removes the predecessor
adapter surface, so the boundaries that asserted adapter-specific
behaviour (B-X1-1, B-X1-4, B-X1-6, B-X1-7, B-X1-8) are dropped here.
The adapter-independent boundaries (B-X1-2, B-X1-3, B-X1-5, B-X1-9)
remain.
"""

import inspect
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# B-X1-2: spec 011 v2 schema unchanged after migrate_to_v3
# ---------------------------------------------------------------------------

def test_b_x1_2_v2_schema_unchanged_after_migrate_to_v3(tmp_path: Path) -> None:
    """B-X1-2: spec 011 v2 schema tables/columns are untouched after migrate_to_v3."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT, duration_sec REAL)"
        )
        conn.execute(
            "CREATE TABLE matches (id INTEGER PRIMARY KEY, video_a TEXT, video_b TEXT, score REAL)"
        )
        conn.execute("INSERT INTO videos VALUES ('aaaaaaaaaaa', 'UCtest', 120.0)")
        conn.execute("PRAGMA user_version = 2")
        conn.commit()

    migrate_to_v3(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id = 'aaaaaaaaaaa'"
        ).fetchone()
        assert row is not None
        assert row[0] == "aaaaaaaaaaa"

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "audio_fingerprint" in tables

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 3


# ---------------------------------------------------------------------------
# B-X1-3: audio_fingerprint table schema frozen (no field deletion/rename)
# ---------------------------------------------------------------------------

def test_b_x1_3_audio_fingerprint_schema_frozen(tmp_path: Path) -> None:
    """B-X1-3: audio_fingerprint table has exactly the contracted columns."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT, duration_sec REAL)"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()

    migrate_to_v3(db_path)

    with sqlite3.connect(db_path) as conn:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(audio_fingerprint)").fetchall()
        }

    required_cols = {"video_id", "fingerprint", "duration", "extracted_at", "source"}
    assert required_cols <= cols, (
        f"B-X1-3: audio_fingerprint missing columns: {required_cols - cols}"
    )


# ---------------------------------------------------------------------------
# B-X1-5: spec 009 OAuth token path unchanged by spec X1
# ---------------------------------------------------------------------------

def test_b_x1_5_spec009_token_path_unchanged() -> None:
    """B-X1-5: spec 009 token directory default path is ~/.config/tube-scout/tokens/."""
    import os
    import re

    from tube_scout.services.auth import _tokens_dir  # type: ignore[attr-defined]

    env_without_override = {
        k: v for k, v in os.environ.items() if k != "TUBE_SCOUT_TOKENS_DIR"
    }
    with patch.dict(os.environ, env_without_override, clear=True):
        tokens_dir = _tokens_dir()

    pattern = re.compile(r"\.config[/\\]tube-scout[/\\]tokens$")
    assert pattern.search(str(tokens_dir)), (
        f"B-X1-5: Tokens dir does not match spec 009 convention: {tokens_dir}"
    )


# ---------------------------------------------------------------------------
# B-X1-9: text SHA fingerprint module and audio fingerprint module coexist
# ---------------------------------------------------------------------------

def test_b_x1_9_text_audio_fingerprint_modules_isolated() -> None:
    """B-X1-9: spec 011 fingerprint.py and audio_fingerprint.py have no public name collision."""
    import tube_scout.services.audio_fingerprint as audio_fp_module
    import tube_scout.services.fingerprint as text_fp_module

    text_members = {
        name for name, _ in inspect.getmembers(text_fp_module, inspect.isfunction)
    }
    audio_members = {
        name for name, _ in inspect.getmembers(audio_fp_module, inspect.isfunction)
    }

    collision = text_members & audio_members
    public_collision = {n for n in collision if not n.startswith("_")}

    assert len(public_collision) == 0, (
        f"B-X1-9: Public function name collision between fingerprint.py and "
        f"audio_fingerprint.py: {public_collision}"
    )
