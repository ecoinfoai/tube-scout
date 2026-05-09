"""Contract tests for spec 011 v2 DB schema migration.

Ground truth: specs/011-reuse-fullstack-subtitle/contracts/db_schema.md §8.
All tests use deterministic fixture builders from tests/fixtures/spec011/fixture_db.py.
"""

import hashlib
import sqlite3

import pytest

from tests.fixtures.spec011.fixture_db import (
    build_clean_v2_db,
    build_spec007_legacy_db,
)
from tube_scout.storage.content_db import migrate_to_v2

_SPEC007_COLUMNS = (
    "id", "source_video_id", "target_video_id", "professor", "course",
    "week", "session", "year_from", "year_to", "i1_hash_match",
    "i2_cosine_similarity", "i3_change_rate", "i4_new_term_count",
    "i5_duration_diff_seconds", "suspicion_score", "grade", "review_status",
)

_NEW_COLUMNS = (
    "matching_mode", "professor_id",
    "i6_longest_contiguous_seconds", "i7_distribution_dispersion", "i8_position_diversity",
    "reuse_pattern", "layer_attribution",
    "baseline_subtracted_length_seconds", "pre_subtraction_i2", "pre_subtraction_i6",
)

_NEW_TABLES = (
    "professor_pool", "professor_pool_membership", "baseline_corpus",
    "phrase_whitelist", "pair_checkpoint", "match_spans", "_schema_version",
)

_NEW_INDEXES = (
    "idx_cr_mode", "idx_cr_prof", "idx_cr_pattern", "idx_span_cmp",
)


def _col_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {row[0] for row in rows}


def _row_hash(row: sqlite3.Row) -> str:
    fields = tuple(row[col] for col in _SPEC007_COLUMNS if col != "id")
    return hashlib.sha256(str(fields).encode()).hexdigest()


def test_migration_idempotent(tmp_path: pytest.TempPathFactory) -> None:
    """Calling migrate_to_v2 twice on a v2 DB must be a no-op with no errors."""
    db = build_clean_v2_db(tmp_path / "v2.db")
    conn = sqlite3.connect(str(db))
    cols_before = _col_names(conn, "comparison_results")
    tables_before = _table_names(conn)
    conn.close()

    migrate_to_v2(db)
    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    cols_after = _col_names(conn, "comparison_results")
    tables_after = _table_names(conn)
    conn.close()

    assert cols_before == cols_after
    assert tables_before == tables_after


def test_alter_columns_present(tmp_path: pytest.TempPathFactory) -> None:
    """All 10 new columns must exist in comparison_results after migration."""
    db = build_spec007_legacy_db(tmp_path / "legacy.db")
    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    cols = _col_names(conn, "comparison_results")
    conn.close()

    for col in _NEW_COLUMNS:
        assert col in cols, f"Missing column: {col}"


def test_new_tables_created(tmp_path: pytest.TempPathFactory) -> None:
    """All 7 new tables must exist after migration."""
    db = build_spec007_legacy_db(tmp_path / "legacy.db")
    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    tables = _table_names(conn)
    conn.close()

    for table in _NEW_TABLES:
        assert table in tables, f"Missing table: {table}"


def test_indexes_created(tmp_path: pytest.TempPathFactory) -> None:
    """All 4 new indexes must exist after migration."""
    db = build_spec007_legacy_db(tmp_path / "legacy.db")
    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    indexes = _index_names(conn)
    conn.close()

    for idx in _NEW_INDEXES:
        assert idx in indexes, f"Missing index: {idx}"


def test_check_constraints_reject_bad_enums(tmp_path: pytest.TempPathFactory) -> None:
    """CHECK constraints must reject invalid enum values after migration.

    Note: SQLite ALTER TABLE cannot add CHECK constraints, so matching_mode
    CHECK on comparison_results is enforced by the service layer (Pydantic),
    not the DB. pair_checkpoint.status CHECK is verified here because
    migrate_to_v2 creates that table with the constraint.
    """
    db = build_spec007_legacy_db(tmp_path / "legacy.db")
    migrate_to_v2(db)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO pair_checkpoint
                (run_id, professor_id, matching_mode, pair_count_total,
                 pair_count_done, started_at, status)
            VALUES ('run-x', 'prof-x', 'M-nC2', 10, 0, '2026-01-01', 'invalid_status')
            """
        )
        conn.commit()

    conn.close()


def test_spec007_row_preservation(tmp_path: pytest.TempPathFactory) -> None:
    """spec 007 row values must not change after migration (hash comparison)."""
    db = build_spec007_legacy_db(tmp_path / "legacy.db")

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    before = {
        row["id"]: _row_hash(row)
        for row in conn.execute("SELECT * FROM comparison_results").fetchall()
    }
    conn.close()

    assert len(before) == 10, f"Expected 10 legacy rows, got {len(before)}"

    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    after = {
        row["id"]: _row_hash(row)
        for row in conn.execute("SELECT * FROM comparison_results").fetchall()
    }
    conn.close()

    assert before == after, "spec 007 column values changed after migration (boundary B-2 violation)"


def test_matching_mode_backfill(tmp_path: pytest.TempPathFactory) -> None:
    """All pre-existing rows must have matching_mode='M-default' after migration."""
    db = build_spec007_legacy_db(tmp_path / "legacy.db")
    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT matching_mode FROM comparison_results").fetchall()
    conn.close()

    assert len(rows) == 10
    for row in rows:
        assert row[0] == "M-default", f"Expected M-default, got {row[0]}"


def test_schema_version_stamp(tmp_path: pytest.TempPathFactory) -> None:
    """_schema_version must contain spec-011/v1 after migration."""
    db = build_spec007_legacy_db(tmp_path / "legacy.db")
    migrate_to_v2(db)

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT spec, version FROM _schema_version WHERE spec = 'spec-011'"
    ).fetchone()
    conn.close()

    assert row is not None, "_schema_version row for spec-011 not found"
    assert row[0] == "spec-011"
    assert row[1] == "v1"
