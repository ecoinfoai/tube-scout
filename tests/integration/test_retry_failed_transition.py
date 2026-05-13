"""T055 RED — C-5: retry_failed allows asr_failed → asr_in_progress transition."""
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processing_status (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL DEFAULT 'UCtest',
    status TEXT NOT NULL DEFAULT 'pending',
    caption_source TEXT,
    error_message TEXT,
    collected_at TEXT,
    fingerprinted_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _setup_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL;")


def _insert_row(db_path: Path, video_id: str, status: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at)"
            " VALUES (?, 'UCtest', ?, datetime('now'))",
            (video_id, status),
        )


def test_retry_failed_false_skips_asr_failed_rows(tmp_path: Path) -> None:
    """With retry_failed=False, asr_failed rows are NOT claimed."""
    from tube_scout.services.worker_pool import _atomic_claim

    db = tmp_path / "content_reuse.db"
    _setup_db(db)

    _insert_row(db, "RETRY_TEST_001", "asr_failed")

    claimed = _atomic_claim(db, retry_failed=False)
    assert claimed is None, f"Expected None but got {claimed!r}"


def test_retry_failed_true_claims_asr_failed_rows(tmp_path: Path) -> None:
    """With retry_failed=True, asr_failed rows ARE claimed (C-5)."""
    from tube_scout.services.worker_pool import _atomic_claim

    db = tmp_path / "content_reuse.db"
    _setup_db(db)

    _insert_row(db, "RETRY_TEST_002", "asr_failed")

    claimed = _atomic_claim(db, retry_failed=True)
    assert claimed == "RETRY_TEST_002"


def test_retry_failed_sets_status_to_asr_in_progress(tmp_path: Path) -> None:
    """After claiming asr_failed row, status transitions to asr_in_progress."""
    from tube_scout.services.worker_pool import _atomic_claim

    db = tmp_path / "content_reuse.db"
    _setup_db(db)

    _insert_row(db, "RETRY_TEST_003", "asr_failed")

    _atomic_claim(db, retry_failed=True)

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status FROM processing_status WHERE video_id = ?", ("RETRY_TEST_003",)
        ).fetchone()

    assert row is not None
    assert row[0] == "asr_in_progress"


def test_retry_failed_sequential_claims_distinct_rows(tmp_path: Path) -> None:
    """Two sequential claims with retry_failed=True each get a distinct row."""
    from tube_scout.services.worker_pool import _atomic_claim

    db = tmp_path / "content_reuse.db"
    _setup_db(db)

    _insert_row(db, "RETRY_TEST_004", "asr_failed")
    _insert_row(db, "RETRY_TEST_005", "asr_failed")

    first = _atomic_claim(db, retry_failed=True)
    second = _atomic_claim(db, retry_failed=True)

    assert first is not None
    assert second is not None
    assert first != second


def test_retry_failed_and_collected_both_claimable(tmp_path: Path) -> None:
    """retry_failed=True claims both 'collected' and 'asr_failed' rows."""
    from tube_scout.services.worker_pool import _atomic_claim

    db = tmp_path / "content_reuse.db"
    _setup_db(db)

    _insert_row(db, "RETRY_COLLECTED", "collected")
    _insert_row(db, "RETRY_FAILED", "asr_failed")

    claimed = set()
    for _ in range(3):
        result = _atomic_claim(db, retry_failed=True)
        if result:
            claimed.add(result)

    assert "RETRY_COLLECTED" in claimed
    assert "RETRY_FAILED" in claimed
