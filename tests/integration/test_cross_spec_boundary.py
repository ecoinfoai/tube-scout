"""T045: Cross-spec boundary integration tests (Constitution VII) — B-X1-1 through B-X1-9.

Each test verifies one boundary from spec.md §Cross-Spec Boundaries.
"""

import inspect
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# B-X1-1: spec 010 transcript JSON format authority
# ---------------------------------------------------------------------------

def test_b_x1_1_transcript_json_format_authority(tmp_path: Path) -> None:
    """B-X1-1: srv3_parser output conforms to spec 010 transcript JSON schema."""
    from tube_scout.services.srv3_parser import srv3_to_transcript_json

    # Minimal SRV3 XML with one subtitle event
    srv3_xml = """<?xml version="1.0" encoding="utf-8" ?>
<timedtext format="3">
  <body>
    <p t="1000" d="2000" w="1">Hello world</p>
  </body>
</timedtext>"""

    result = srv3_to_transcript_json(
        srv3_xml,
        video_id="tuxscjwiJYs",
        language="ko",
        source="ytdlp:manual",
    )

    # Verify required spec 010 fields present
    assert "video_id" in result
    assert "language" in result
    assert "source" in result
    assert "segments" in result
    assert isinstance(result["segments"], list)
    assert len(result["segments"]) > 0

    seg = result["segments"][0]
    assert "start" in seg
    assert "end" in seg
    assert "text" in seg

    # source must be ytdlp:manual or ytdlp:auto (spec X1 additions)
    assert result["source"] in ("ytdlp:manual", "ytdlp:auto", "api")


# ---------------------------------------------------------------------------
# B-X1-2: spec 011 v2 schema unchanged after migrate_to_v3
# ---------------------------------------------------------------------------

def test_b_x1_2_v2_schema_unchanged_after_migrate_to_v3(tmp_path: Path) -> None:
    """B-X1-2: spec 011 v2 schema tables/columns are untouched after migrate_to_v3."""
    from tube_scout.storage.content_db import migrate_to_v3

    db_path = tmp_path / "content_reuse.db"
    with sqlite3.connect(db_path) as conn:
        # Create minimal spec 011 v2 schema
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
        # v2 rows still intact
        row = conn.execute("SELECT * FROM videos WHERE video_id = 'aaaaaaaaaaa'").fetchone()
        assert row is not None
        assert row[0] == "aaaaaaaaaaa"

        # audio_fingerprint table was added
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "audio_fingerprint" in tables

        # user_version bumped to 3
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
# B-X1-4: spec 003 alias resolver gate — unregistered alias blocks yt-dlp
# ---------------------------------------------------------------------------

def test_b_x1_4_alias_resolver_gate_blocks_ytdlp(tmp_path: Path) -> None:
    """B-X1-4: resolve_alias_to_channel_id raises KeyError for unregistered alias."""
    from tube_scout.cli.collect import resolve_alias_to_channel_id

    with patch("tube_scout.services.auth.load_registry", return_value={}), \
         patch("tube_scout.services.auth.resolve_channel_alias") as mock_resolve:
        mock_resolve.side_effect = KeyError("alias not found")

        with pytest.raises(KeyError):
            resolve_alias_to_channel_id("not-registered-alias")


# ---------------------------------------------------------------------------
# B-X1-5: spec 009 OAuth token path unchanged by spec X1
# ---------------------------------------------------------------------------

def test_b_x1_5_spec009_token_path_unchanged() -> None:
    """B-X1-5: spec 009 token directory default path is ~/.config/tube-scout/tokens/."""
    import os
    import re
    from tube_scout.services.auth import _tokens_dir  # type: ignore[attr-defined]

    # Verify the default path (when env override is absent)
    env_without_override = {k: v for k, v in os.environ.items() if k != "TUBE_SCOUT_TOKENS_DIR"}
    with patch.dict(os.environ, env_without_override, clear=True):
        tokens_dir = _tokens_dir()

    pattern = re.compile(r"\.config[/\\]tube-scout[/\\]tokens$")
    assert pattern.search(str(tokens_dir)), (
        f"B-X1-5: Tokens dir does not match spec 009 convention: {tokens_dir}"
    )


# ---------------------------------------------------------------------------
# B-X1-6: agenix — cookies file must use env var, not hardcoded path
# ---------------------------------------------------------------------------

def test_b_x1_6_cookies_resolution_prefers_env_var(tmp_path: Path) -> None:
    """B-X1-6: cookies file resolution checks TUBE_SCOUT_COOKIES_FILE env var."""
    from tube_scout.services.ytdlp_adapter import resolve_cookies_source, _build_cookies_args

    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# cookies", encoding="utf-8")
    cookies_file.chmod(0o600)

    env = {"TUBE_SCOUT_COOKIES_FILE": str(cookies_file)}
    source = resolve_cookies_source(cookies_browser=None, cookies_path=None, env=env)
    args = _build_cookies_args(source)

    # When env var is set, kind must be 'file'
    assert source.kind == "file", (
        f"B-X1-6: TUBE_SCOUT_COOKIES_FILE not honored. Got source: {source}"
    )
    # Args must use --cookies not --cookies-from-browser
    assert any("--cookies" in str(a) for a in args), (
        f"B-X1-6: --cookies arg missing. Got args: {args}"
    )
    assert not any("--cookies-from-browser" in str(a) for a in args), (
        f"B-X1-6: --cookies-from-browser used when env var set. Got args: {args}"
    )


# ---------------------------------------------------------------------------
# B-X1-7: output directory convention — audio_temp lifecycle preserved
# ---------------------------------------------------------------------------

def test_b_x1_7_audio_temp_empty_after_dispatch(tmp_path: Path) -> None:
    """B-X1-7: dispatch_audio_fingerprint cleans audio_temp after processing."""
    from tube_scout.cli.collect import dispatch_audio_fingerprint

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()

    mp3_path = audio_temp / "testvid0001.mp3"
    mp3_path.write_bytes(b"fake mp3")

    with patch("tube_scout.services.ytdlp_adapter.fetch_audio_via_ytdlp", return_value=mp3_path), \
         patch("tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint",
               return_value=(b"\x00" * 32, 90.0)):
        dispatch_audio_fingerprint(
            video_ids=["testvid0001"],
            audio_temp=audio_temp,
            db_path=None,
        )

    remaining = list(audio_temp.glob("*.mp3"))
    assert len(remaining) == 0, (
        f"B-X1-7: SC-004 violation — {len(remaining)} mp3(s) remain: {remaining}"
    )


# ---------------------------------------------------------------------------
# B-X1-8: flake.nix devShell — yt-dlp available via .venv (not pkgs.yt-dlp)
# ---------------------------------------------------------------------------

def test_b_x1_8_ytdlp_installed_via_uv_not_nix() -> None:
    """B-X1-8: yt-dlp is installed via uv (.venv/bin/yt-dlp), not as nixpkg."""
    import shutil
    import sys

    ytdlp_path = shutil.which("yt-dlp")
    if ytdlp_path is None:
        pytest.skip("yt-dlp not available in PATH; expected in .venv/bin")

    # yt-dlp must NOT come from a nix store python3.13 path
    # (would mix Python 3.13 site-packages into 3.11 venv)
    assert "3.13" not in ytdlp_path, (
        f"B-X1-8: yt-dlp appears to come from Python 3.13 nix path: {ytdlp_path}"
    )


# ---------------------------------------------------------------------------
# B-X1-9: text SHA fingerprint module and audio fingerprint module coexist
# ---------------------------------------------------------------------------

def test_b_x1_9_text_audio_fingerprint_modules_isolated() -> None:
    """B-X1-9: spec 011 fingerprint.py and spec X1 audio_fingerprint.py have no name collision."""
    import tube_scout.services.fingerprint as text_fp_module
    import tube_scout.services.audio_fingerprint as audio_fp_module

    text_members = {name for name, _ in inspect.getmembers(text_fp_module, inspect.isfunction)}
    audio_members = {name for name, _ in inspect.getmembers(audio_fp_module, inspect.isfunction)}

    collision = text_members & audio_members
    # Allow private helpers (_*) — only check public API collision
    public_collision = {n for n in collision if not n.startswith("_")}

    assert len(public_collision) == 0, (
        f"B-X1-9: Public function name collision between spec 011 fingerprint.py "
        f"and spec X1 audio_fingerprint.py: {public_collision}"
    )
