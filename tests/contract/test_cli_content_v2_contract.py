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


def test_placeholder_whitelist_add_pair_raises_not_implemented(tmp_path: Path) -> None:
    """Invoking an unimplemented placeholder (whitelist add-pair) raises NotImplementedError."""
    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_spec007_legacy_db(db_dir / "content_reuse.db")

    result = runner.invoke(
        content_app,
        [
            "whitelist",
            "add-pair",
            "--project",
            str(tmp_path),
            "--reason",
            "test reason",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
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


# ---------------------------------------------------------------------------
# T052: baseline CLI real impl contract tests (RED)
# ---------------------------------------------------------------------------


def test_baseline_bootstrap_real_impl_inserts_db_rows(tmp_path: Path) -> None:
    """'content baseline bootstrap' with real impl inserts rows into baseline_corpus."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    # Create a professor pool entry + captions dir with fixture data
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-bootstrap', 'Bootstrap Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()

    # Create a captions dir with two caption files containing repeated phrases
    cap_dir = tmp_path / "01_collect" / "transcripts"
    cap_dir.mkdir(parents=True)
    import json
    for i in range(1, 3):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "안녕하세요 여러분"},
            {"start": 5.0, "end": 10.0, "text": "안녕하세요 여러분"},
            {"start": 10.0, "end": 15.0, "text": "안녕하세요 여러분"},
        ]
        (cap_dir / f"vid{i:03d}.json").write_text(
            json.dumps({"video_id": f"vid{i:03d}", "segments": segments}),
            encoding="utf-8",
        )

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        result = runner.invoke(
            content_app,
            [
                "baseline", "bootstrap",
                "--project", str(tmp_path),
                "--professor", "prof-bootstrap",
                "--min-occurrences", "2",
            ],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"Output: {result.output!r}  "
        f"Exception: {result.exception!r}"
    )
    conn = sqlite3.connect(str(db_path))
    count = conn.execute(
        "SELECT COUNT(*) FROM baseline_corpus WHERE professor_id='prof-bootstrap'"
    ).fetchone()[0]
    conn.close()
    assert count >= 1, "baseline_corpus: no rows inserted by 'baseline bootstrap'"


def test_baseline_add_real_impl_inserts_phrase(tmp_path: Path) -> None:
    """'content baseline add' with real impl inserts a phrase into baseline_corpus."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-add', 'Add Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        result = runner.invoke(
            content_app,
            [
                "baseline", "add",
                "--project", str(tmp_path),
                "--professor", "prof-add",
                "--phrase", "반갑습니다 여러분",
            ],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
    )
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT phrase_raw FROM baseline_corpus WHERE professor_id='prof-add'"
    ).fetchone()
    conn.close()
    assert row is not None, "baseline_corpus: phrase not inserted by 'baseline add'"


def test_baseline_list_shows_phrases(tmp_path: Path) -> None:
    """'content baseline list' outputs registered phrases."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-list', 'List Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        runner.invoke(
            content_app,
            [
                "baseline", "add",
                "--project", str(tmp_path),
                "--professor", "prof-list",
                "--phrase", "오늘 배울 내용",
            ],
            catch_exceptions=True,
        )
        result = runner.invoke(
            content_app,
            ["baseline", "list", "--project", str(tmp_path), "--professor", "prof-list"],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    assert "오늘 배울 내용" in result.output or "prof-list" in result.output


def test_baseline_remove_removes_phrase(tmp_path: Path) -> None:
    """'content baseline remove' removes the phrase from baseline_corpus."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES ('prof-remove', 'Remove Prof', '2026-01-01T00:00:00', 'system')"
    )
    conn.commit()
    conn.close()

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        runner.invoke(
            content_app,
            [
                "baseline", "add",
                "--project", str(tmp_path),
                "--professor", "prof-remove",
                "--phrase", "삭제할 구문",
            ],
            catch_exceptions=True,
        )
        result = runner.invoke(
            content_app,
            [
                "baseline", "remove",
                "--project", str(tmp_path),
                "--professor", "prof-remove",
                "--phrase", "삭제할 구문",
            ],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, f"Expected exit 0: {result.output}"
    conn = sqlite3.connect(str(db_path))
    count = conn.execute(
        "SELECT COUNT(*) FROM baseline_corpus WHERE professor_id='prof-remove'"
    ).fetchone()[0]
    conn.close()
    assert count == 0, "baseline_corpus: phrase not removed by 'baseline remove'"


# ---------------------------------------------------------------------------
# T053: policy CLI real impl contract tests (RED)
# ---------------------------------------------------------------------------


def test_policy_show_outputs_yaml_or_default(tmp_path: Path) -> None:
    """'content policy show' exits 0 and outputs YAML or default policy."""
    import tube_scout.cli.content as _content_mod
    import yaml

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_clean_v2_db(db_dir / "content_reuse.db")

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        result = runner.invoke(
            content_app,
            ["policy", "show", "--project", str(tmp_path)],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. Output: {result.output!r}"
    )
    # Output should be valid YAML containing policy keys
    assert "layer_a_min_seconds" in result.output or "composite_weights" in result.output


def test_policy_validate_exits_0_with_valid_yaml(tmp_path: Path) -> None:
    """'content policy validate' exits 0 when policy.yaml is valid."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_clean_v2_db(db_dir / "content_reuse.db")

    # Write a valid policy.yaml
    policy_path = db_dir / "policy.yaml"
    policy_path.write_text(
        "layer_a_min_seconds: 60.0\n"
        "layer_c_evolution_band: [0.60, 0.75]\n"
        "matching_cosine_cull: 0.55\n"
        "pattern_whole_threshold_ratio: 0.50\n"
        "composite_weights:\n"
        "  i1: 0.20\n"
        "  i2: 0.20\n"
        "  i3: 0.10\n"
        "  i4: 0.05\n"
        "  i5: 0.05\n"
        "  i6: 0.20\n"
        "  i7: 0.10\n"
        "  i8: 0.10\n",
        encoding="utf-8",
    )

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        result = runner.invoke(
            content_app,
            ["policy", "validate", "--project", str(tmp_path)],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 0, (
        f"Expected exit 0 for valid policy, got {result.exit_code}. Output: {result.output!r}"
    )


def test_policy_validate_exits_4_with_invalid_yaml(tmp_path: Path) -> None:
    """'content policy validate' exits 4 when policy.yaml has invalid weights."""
    import tube_scout.cli.content as _content_mod

    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    build_clean_v2_db(db_dir / "content_reuse.db")

    # Write an invalid policy.yaml (weights don't sum to 1.0)
    policy_path = db_dir / "policy.yaml"
    policy_path.write_text(
        "layer_a_min_seconds: 60.0\n"
        "layer_c_evolution_band: [0.60, 0.75]\n"
        "composite_weights:\n"
        "  i1: 0.99\n"
        "  i2: 0.99\n",
        encoding="utf-8",
    )

    original_flag = _content_mod._SPEC011_MIGRATED
    _content_mod._SPEC011_MIGRATED = True
    try:
        result = runner.invoke(
            content_app,
            ["policy", "validate", "--project", str(tmp_path)],
            catch_exceptions=True,
        )
    finally:
        _content_mod._SPEC011_MIGRATED = original_flag

    assert result.exit_code == 4, (
        f"Expected exit 4 for invalid policy, got {result.exit_code}. Output: {result.output!r}"
    )
