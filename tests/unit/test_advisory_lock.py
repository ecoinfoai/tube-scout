"""Unit tests for advisory_lock service (T011 RED).

Tests verify SQLite BEGIN IMMEDIATE lock acquisition, concurrent rejection,
exception-safe release, and commit on normal exit.
"""

import sqlite3
import threading
from pathlib import Path

import pytest

from tube_scout.services.advisory_lock import (
    ConcurrentWriteRejected,
    layer_d_write_lock,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_table (
    id INTEGER PRIMARY KEY,
    val TEXT NOT NULL
);
"""


def _make_db(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.close()
    return path


def test_first_writer_acquires(tmp_path: Path) -> None:
    """Lock acquisition succeeds and INSERT is visible after context exit."""
    db = _make_db(tmp_path / "test.db")
    with layer_d_write_lock(db) as conn:
        conn.execute("INSERT INTO test_table (val) VALUES ('hello')")

    verify = sqlite3.connect(str(db))
    row = verify.execute("SELECT val FROM test_table WHERE val='hello'").fetchone()
    verify.close()
    assert row is not None


def test_second_concurrent_writer_rejected(tmp_path: Path) -> None:
    """A second writer on the same DB during an active lock raises ConcurrentWriteRejected."""
    db = _make_db(tmp_path / "test.db")
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def first_writer() -> None:
        with layer_d_write_lock(db) as conn:
            conn.execute("INSERT INTO test_table (val) VALUES ('first')")
            barrier.wait()   # signal second writer to attempt
            barrier.wait()   # wait until second writer has tried

    def second_writer() -> None:
        barrier.wait()  # wait until first writer has lock
        try:
            with layer_d_write_lock(db):
                pass
        except ConcurrentWriteRejected as exc:
            errors.append(exc)
        finally:
            barrier.wait()  # signal first writer to finish

    t1 = threading.Thread(target=first_writer)
    t2 = threading.Thread(target=second_writer)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(errors) == 1
    assert isinstance(errors[0], ConcurrentWriteRejected)
    assert "retry" in str(errors[0]).lower() or "administrator" in str(errors[0]).lower()


def test_lock_released_on_exception(tmp_path: Path) -> None:
    """Lock is released even when the context body raises an exception."""
    db = _make_db(tmp_path / "test.db")

    with pytest.raises(RuntimeError, match="intentional"):
        with layer_d_write_lock(db):
            raise RuntimeError("intentional")

    # Lock must be released — a subsequent acquire must succeed
    with layer_d_write_lock(db) as conn:
        conn.execute("INSERT INTO test_table (val) VALUES ('after_error')")

    verify = sqlite3.connect(str(db))
    row = verify.execute("SELECT val FROM test_table WHERE val='after_error'").fetchone()
    verify.close()
    assert row is not None


def test_normal_exit_commits(tmp_path: Path) -> None:
    """Changes are persisted to disk after normal context exit."""
    db = _make_db(tmp_path / "test.db")

    with layer_d_write_lock(db) as conn:
        conn.execute("INSERT INTO test_table (val) VALUES ('committed')")

    # Open a fresh connection to confirm durability
    verify = sqlite3.connect(str(db))
    count = verify.execute(
        "SELECT COUNT(*) FROM test_table WHERE val='committed'"
    ).fetchone()[0]
    verify.close()
    assert count == 1
