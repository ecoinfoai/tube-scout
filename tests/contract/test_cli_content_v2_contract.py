"""Contract tests for CLI content command v2 shape (T017-T018 RED).

Verifies that spec 011 subcommand groups exist under 'tube-scout content',
that all placeholder commands are registered, and that the lazy
migrate_to_v2 startup hook fires on the first spec 011 command call.
"""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.fixtures.spec011.fixture_db import build_spec007_legacy_db
from tube_scout.cli.content import content_app


runner = CliRunner()


def test_professor_subcommand_exists() -> None:
    """'content professor --help' exits 0 and lists map/list/show/unmap."""
    result = runner.invoke(content_app, ["professor", "--help"])
    assert result.exit_code == 0, result.output
    output = result.output.lower()
    assert "map" in output
    assert "list" in output
    assert "show" in output
    assert "unmap" in output


def test_baseline_subcommand_exists() -> None:
    """'content baseline --help' exits 0 and lists bootstrap/add/list/remove."""
    result = runner.invoke(content_app, ["baseline", "--help"])
    assert result.exit_code == 0, result.output
    output = result.output.lower()
    assert "bootstrap" in output
    assert "add" in output
    assert "list" in output
    assert "remove" in output


def test_whitelist_subcommand_exists() -> None:
    """'content whitelist --help' exits 0 and lists add-pair/add-phrase/list/export/remove."""
    result = runner.invoke(content_app, ["whitelist", "--help"])
    assert result.exit_code == 0, result.output
    output = result.output.lower()
    assert "add-pair" in output
    assert "add-phrase" in output
    assert "list" in output
    assert "export" in output
    assert "remove" in output


def test_policy_subcommand_exists() -> None:
    """'content policy --help' exits 0 and lists show/validate."""
    result = runner.invoke(content_app, ["policy", "--help"])
    assert result.exit_code == 0, result.output
    output = result.output.lower()
    assert "show" in output
    assert "validate" in output


def test_placeholder_raises_not_implemented(tmp_path: Path) -> None:
    """Invoking a placeholder command raises NotImplementedError with actionable message."""
    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_spec007_legacy_db(db_dir / "content_reuse.db")

    result = runner.invoke(
        content_app,
        [
            "professor",
            "map",
            "--project",
            str(tmp_path),
            "--professor-id",
            "prof-x",
            "--display-name",
            "Prof X",
            "--channel",
            "ch-test",
            "--author",
            "__channel_owner__",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    # typer wraps NotImplementedError — check the exception directly
    assert isinstance(result.exception, NotImplementedError)
    msg = str(result.exception).lower()
    assert "not yet implemented" in msg or "pending" in msg


def test_migrate_runs_on_first_spec011_command(tmp_path: Path) -> None:
    """First spec 011 command call triggers migrate_to_v2 on the project DB.

    Places a legacy spec 007 DB in the project directory, invokes
    'content policy show', then checks that spec 011 tables were created.
    """
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_spec007_legacy_db(db_path)

    # Verify that spec 011 tables do NOT exist yet
    conn = sqlite3.connect(str(db_path))
    tables_before = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "professor_pool" not in tables_before

    # Reset the module-level migration flag so the hook fires in this test
    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = False
    try:
        result = runner.invoke(
            content_app,
            ["policy", "show", "--project", str(tmp_path)],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    # Command may exit non-zero (NotImplementedError) but migration must run first
    # We only check that spec 011 tables now exist in the DB
    conn = sqlite3.connect(str(db_path))
    tables_after = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "professor_pool" in tables_after, (
        f"migrate_to_v2 was not called: professor_pool table missing. "
        f"Command output: {result.output}"
    )
    assert "pair_checkpoint" in tables_after
