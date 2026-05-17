"""Unit tests — _add_column_if_missing helper (spec 013 T006).

Updated 2026-05-17 (audit v3 F-24 / SEC-1): the helper now rejects any
``(table, column)`` pair not in ``_V4_ALTER_ALLOWED`` to prevent DDL
identifier injection via f-string interpolation. Tests exercise the
allowlisted v4 columns instead of synthetic ``t.new_col``.
"""

from __future__ import annotations

import sqlite3

import pytest


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return [row[1] for row in cur.fetchall()]


def test_adds_column_when_missing() -> None:
    """Allowlisted column absent → added, visible via PRAGMA table_info."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE processing_status (video_id TEXT PRIMARY KEY);")
        cur = conn.cursor()
        _add_column_if_missing(cur, "processing_status", "match_confidence", "TEXT")
        assert "match_confidence" in _column_names(conn, "processing_status")


def test_no_op_when_column_exists() -> None:
    """Allowlisted column already present → no exception, table unchanged."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE processing_status "
            "(video_id TEXT PRIMARY KEY, match_confidence TEXT);"
        )
        cur = conn.cursor()
        before = _column_names(conn, "processing_status")
        _add_column_if_missing(cur, "processing_status", "match_confidence", "TEXT")
        after = _column_names(conn, "processing_status")
        assert before == after


def test_returns_correct_boolean() -> None:
    """Returns True when column added, False when column already existed."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE quality_results (video_id TEXT PRIMARY KEY);")
        cur = conn.cursor()
        assert _add_column_if_missing(
            cur, "quality_results", "asr_quality_flags", "TEXT"
        ) is True
        assert _add_column_if_missing(
            cur, "quality_results", "asr_quality_flags", "TEXT"
        ) is False


def test_rejects_identifier_not_in_allowlist() -> None:
    """Non-allowlisted (table, column) → ValueError (SEC-1 guard)."""
    from tube_scout.storage.content_db import _add_column_if_missing

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
        cur = conn.cursor()
        with pytest.raises(ValueError, match="not in v4 allowlist"):
            _add_column_if_missing(cur, "t", "new_col", "TEXT")
