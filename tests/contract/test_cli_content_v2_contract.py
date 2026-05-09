"""Contract tests for CLI content command v2 shape (T017-T019 RED).

Verifies that spec 011 subcommand groups exist under 'tube-scout content',
that all placeholder commands are registered, the lazy migrate_to_v2 startup
hook fires on the first spec 011 command call, and that mode/professor options
are wired correctly (T019).
"""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.fixtures.spec011.fixture_db import build_clean_v2_db, build_spec007_legacy_db
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


# ---------------------------------------------------------------------------
# T019: mode option contract tests (RED — real impl not yet wired)
# ---------------------------------------------------------------------------


def test_scan_accepts_mode_nc2_with_professor(tmp_path: Path) -> None:
    """'content scan --mode nc2 --professor <id>' accepted (no option-parse error)."""
    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_clean_v2_db(db_dir / "content_reuse.db")

    result = runner.invoke(
        content_app,
        [
            "scan",
            "--project", str(tmp_path),
            "--mode", "nc2",
            "--professor", "prof-x",
            "--year-from", "2024",
            "--year-to", "2025",
            "--channel", "ch-test",
        ],
        catch_exceptions=True,
    )
    # Must not fail due to unknown option — any exit code except 2 (typer usage error) is OK
    assert result.exit_code != 2 or "no such option" not in (result.output or "").lower(), (
        f"--mode option not recognized: {result.output}"
    )


def test_scan_nc2_missing_professor_exits_nonzero(tmp_path: Path) -> None:
    """'content scan --mode nc2' without --professor exits with non-zero code + actionable message."""
    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_clean_v2_db(db_dir / "content_reuse.db")

    result = runner.invoke(
        content_app,
        [
            "scan",
            "--project", str(tmp_path),
            "--mode", "nc2",
            "--year-from", "2024",
            "--year-to", "2025",
            "--channel", "ch-test",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    output = result.output.lower()
    assert "professor" in output or (
        result.exception is not None and "professor" in str(result.exception).lower()
    )


def test_professor_map_actually_inserts_db_row(tmp_path: Path) -> None:
    """'content professor map' with real impl inserts a row into professor_pool."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True  # skip re-migration
    try:
        result = runner.invoke(
            content_app,
            [
                "professor", "map",
                "--project", str(tmp_path),
                "--professor-id", "prof-test",
                "--display-name", "Test Prof",
                "--channel", "ch-a",
                "--author", "__channel_owner__",
            ],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.output}"
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT professor_id FROM professor_pool WHERE professor_id='prof-test'"
    ).fetchone()
    conn.close()
    assert row is not None, "professor_pool row not inserted by 'professor map' command"


def test_professor_list_shows_registered_mappings(tmp_path: Path) -> None:
    """'content professor list' shows previously registered mappings."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        runner.invoke(
            content_app,
            [
                "professor", "map",
                "--project", str(tmp_path),
                "--professor-id", "prof-list-test",
                "--display-name", "List Prof",
                "--channel", "ch-b",
                "--author", "__channel_owner__",
            ],
            catch_exceptions=True,
        )
        result = runner.invoke(
            content_app,
            ["professor", "list", "--project", str(tmp_path)],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    assert "prof-list-test" in result.output


def test_professor_unmap_removes_db_row(tmp_path: Path) -> None:
    """'content professor unmap' removes the membership row from the DB."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        runner.invoke(
            content_app,
            [
                "professor", "map",
                "--project", str(tmp_path),
                "--professor-id", "prof-unmap",
                "--display-name", "Unmap Prof",
                "--channel", "ch-c",
                "--author", "__channel_owner__",
            ],
            catch_exceptions=True,
        )
        result = runner.invoke(
            content_app,
            [
                "professor", "unmap",
                "--project", str(tmp_path),
                "--professor-id", "prof-unmap",
                "--channel", "ch-c",
                "--author", "__channel_owner__",
            ],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT 1 FROM professor_pool_membership WHERE professor_id='prof-unmap'"
    ).fetchone()
    conn.close()
    assert row is None, "professor_pool_membership row not removed by 'professor unmap' command"
