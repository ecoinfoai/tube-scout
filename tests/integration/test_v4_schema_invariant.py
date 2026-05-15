"""B-4 Cross-Spec Boundary: SQLite v4 schema column-set invariant.

Verifies that the five spec-013 tables (channel_metadata, video_metadata,
processing_status, quality_results, comparison_results) expose exactly the
column names recorded in tests/fixtures/v0_5_0_schema_snapshot.sql after
spec-016 migration, and that PRAGMA user_version is still 4.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
from pathlib import Path

import pytest

_SNAPSHOT_PATH = (
    Path(__file__).parent.parent / "fixtures" / "v0_5_0_schema_snapshot.sql"
)
_TARGET_TABLES = {
    "channel_metadata",
    "video_metadata",
    "processing_status",
    "quality_results",
    "comparison_results",
}


def _parse_snapshot_columns(sql_path: Path) -> dict[str, list[str]]:
    """Return {table_name: [col_name, ...]} from the snapshot SQL file."""
    text = sql_path.read_text()
    result: dict[str, list[str]] = {}
    for m in re.finditer(r"CREATE TABLE (\w+)\s*\((.+?)\);", text, re.DOTALL):
        table = m.group(1)
        if table not in _TARGET_TABLES:
            continue
        body = m.group(2)
        cols: list[str] = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            upper = line.upper()
            if not line or upper.startswith(
                ("FOREIGN KEY", "UNIQUE ", "PRIMARY KEY", "CHECK ", "CONSTRAINT ", "--")
            ):
                continue
            col_name = line.split()[0]
            if col_name:
                cols.append(col_name)
        result[table] = cols
    return result


def _live_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


@pytest.fixture()
def v4_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite v4 database using the same bootstrap path as takeout_ingest."""
    db_path = tmp_path / "test_invariant.db"
    from tube_scout.services.takeout_ingest import _ensure_v4  # type: ignore[attr-defined]
    _ensure_v4(db_path)
    return db_path


class TestV4SchemaInvariant:
    def test_user_version_is_4(self, v4_db: Path) -> None:
        conn = sqlite3.connect(v4_db)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 4

    def test_target_tables_exist(self, v4_db: Path) -> None:
        conn = sqlite3.connect(v4_db)
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        missing = _TARGET_TABLES - names
        assert not missing, f"Missing tables: {missing}"

    @pytest.mark.parametrize("table", sorted(_TARGET_TABLES))
    def test_column_set_matches_snapshot(self, v4_db: Path, table: str) -> None:
        snapshot = _parse_snapshot_columns(_SNAPSHOT_PATH)
        assert table in snapshot, f"Table {table!r} not in snapshot file"
        expected = set(snapshot[table])

        conn = sqlite3.connect(v4_db)
        actual = set(_live_columns(conn, table))
        conn.close()

        missing = expected - actual
        extra = actual - expected
        assert not missing, f"{table}: columns missing vs snapshot: {missing}"
        assert not extra, f"{table}: extra columns not in snapshot: {extra}"
