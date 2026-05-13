"""Unit tests — SQLite atomic claim for worker_pool (spec 013 T049 RED).

FR-022 + C-5: _atomic_claim correctness, status transitions, retry_failed predicate,
concurrent thread safety.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processing_status (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    caption_source TEXT,
    error_message TEXT,
    collected_at TEXT,
    fingerprinted_at TEXT,
    updated_at TEXT NOT NULL
);
"""


def _create_test_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL;")


def _insert_row(db_path: Path, video_id: str, status: str, caption_source: str | None = None) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO processing_status"
            " (video_id, channel_id, status, caption_source, updated_at)"
            " VALUES (?, 'UCtest', ?, ?, datetime('now'))",
            (video_id, status, caption_source),
        )


# ---------------------------------------------------------------------------
# T049-1: _atomic_claim returns one row per call
# ---------------------------------------------------------------------------

def test_atomic_claim_returns_one_row_per_call(tmp_path: Path) -> None:
    """_atomic_claim returns a video_id on first call, None when queue is empty."""
    from tube_scout.services.worker_pool import _atomic_claim

    db_path = tmp_path / "test.db"
    _create_test_db(db_path)
    _insert_row(db_path, "VID001", "collected")
    _insert_row(db_path, "VID002", "collected")

    claimed1 = _atomic_claim(db_path, retry_failed=False)
    assert claimed1 is not None, "First claim must return a video_id"

    claimed2 = _atomic_claim(db_path, retry_failed=False)
    assert claimed2 is not None, "Second claim must return the remaining video_id"
    assert claimed1 != claimed2, "Two claims must return different video_ids"

    claimed3 = _atomic_claim(db_path, retry_failed=False)
    assert claimed3 is None, "Third claim must return None (queue empty)"


# ---------------------------------------------------------------------------
# T049-2: _atomic_claim updates status to asr_in_progress
# ---------------------------------------------------------------------------

def test_atomic_claim_updates_status_to_in_progress(tmp_path: Path) -> None:
    """Claimed row must have status='asr_in_progress' after _atomic_claim."""
    from tube_scout.services.worker_pool import _atomic_claim

    db_path = tmp_path / "test.db"
    _create_test_db(db_path)
    _insert_row(db_path, "VID001", "collected")

    video_id = _atomic_claim(db_path, retry_failed=False)
    assert video_id == "VID001"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM processing_status WHERE video_id = ?", (video_id,)
        ).fetchone()
    assert row is not None
    assert row[0] == "asr_in_progress", (
        f"Status must be 'asr_in_progress' after claim, got: {row[0]}"
    )


# ---------------------------------------------------------------------------
# T049-3: _atomic_claim with retry_failed=True includes asr_failed rows
# ---------------------------------------------------------------------------

def test_atomic_claim_retry_failed_extends_predicate(tmp_path: Path) -> None:
    """retry_failed=True allows claiming asr_failed rows directly (C-5)."""
    from tube_scout.services.worker_pool import _atomic_claim

    db_path = tmp_path / "test.db"
    _create_test_db(db_path)
    _insert_row(db_path, "VID_FAILED", "asr_failed")

    # Without retry_failed, asr_failed row is not claimable
    claimed = _atomic_claim(db_path, retry_failed=False)
    assert claimed is None, "asr_failed row must not be claimed when retry_failed=False"

    # With retry_failed, asr_failed → asr_in_progress directly
    claimed = _atomic_claim(db_path, retry_failed=True)
    assert claimed == "VID_FAILED", (
        f"asr_failed row must be claimed when retry_failed=True, got: {claimed}"
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM processing_status WHERE video_id = ?", ("VID_FAILED",)
        ).fetchone()
    assert row[0] == "asr_in_progress", (
        f"asr_failed → asr_in_progress direct transition required, got: {row[0]}"
    )


# ---------------------------------------------------------------------------
# T049-4: concurrent claim — two threads, only one succeeds per row
# ---------------------------------------------------------------------------

def test_concurrent_claim_two_threads_succeeds_for_one_only(tmp_path: Path) -> None:
    """Two threads simultaneously calling _atomic_claim claim distinct rows (no duplication)."""
    from tube_scout.services.worker_pool import _atomic_claim

    db_path = tmp_path / "test.db"
    _create_test_db(db_path)
    # Insert exactly 2 rows — each thread should claim exactly 1
    _insert_row(db_path, "VID_A", "collected")
    _insert_row(db_path, "VID_B", "collected")

    claimed: list[str | None] = []
    lock = threading.Lock()

    def worker():
        result = _atomic_claim(db_path, retry_failed=False)
        with lock:
            claimed.append(result)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    non_none = [c for c in claimed if c is not None]
    assert len(non_none) == 2, (
        f"Both threads must claim distinct rows, got: {claimed}"
    )
    assert len(set(non_none)) == 2, (
        f"Claimed video_ids must be distinct (no duplication), got: {claimed}"
    )
