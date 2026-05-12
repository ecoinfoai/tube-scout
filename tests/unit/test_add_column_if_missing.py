"""Unit tests — _add_column_if_missing helper (spec 013 T006)."""

from __future__ import annotations

import sqlite3


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return [row[1] for row in cur.fetchall()]


def test_adds_column_when_missing() -> None:
    """Column absent from table → added, visible via PRAGMA table_info."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
        cur = conn.cursor()
        _add_column_if_missing(cur, "t", "new_col", "TEXT")
        assert "new_col" in _column_names(conn, "t")


def test_no_op_when_column_exists() -> None:
    """Column already present → no exception, table unchanged."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, existing TEXT);")
        cur = conn.cursor()
        before = _column_names(conn, "t")
        _add_column_if_missing(cur, "t", "existing", "TEXT")
        after = _column_names(conn, "t")
        assert before == after


def test_returns_correct_boolean() -> None:
    """Returns True when column added, False when column already existed."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
        cur = conn.cursor()
        assert _add_column_if_missing(cur, "t", "new_col", "TEXT") is True
        assert _add_column_if_missing(cur, "t", "new_col", "TEXT") is False
