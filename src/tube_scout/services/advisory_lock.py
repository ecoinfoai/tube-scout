"""Advisory write lock for Layer D review-state mutations.

Uses SQLite BEGIN IMMEDIATE to serialise concurrent admin writes.
Retry policy: zero retries — immediate rejection on contention (R-6).
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOCKED_MESSAGE = (
    "Another administrator is currently writing to the review state. "
    "Please retry in a moment."
)


class ConcurrentWriteRejected(RuntimeError):
    """Raised when another administrator's write is in progress.

    The user-facing surface (CLI / web) must translate this to exit
    code 3 / HTTP 409 Conflict. Always contains the standard English
    message defined in contracts/cli_content.md §11.
    """


@contextmanager
def layer_d_write_lock(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Acquire a SQLite BEGIN IMMEDIATE write lock for Layer D mutations.

    Opens a dedicated connection, issues BEGIN IMMEDIATE (fails instantly
    if another writer holds the lock), yields the connection, then commits
    on clean exit or rolls back on any exception.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        An open sqlite3.Connection inside an active transaction.

    Raises:
        TypeError: If db_path is not a Path instance.
        ConcurrentWriteRejected: If another connection already holds a
            write lock on the database (zero-retry policy per R-6).
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path), timeout=0)
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise ConcurrentWriteRejected(_LOCKED_MESSAGE) from exc
            raise
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
    finally:
        conn.close()
