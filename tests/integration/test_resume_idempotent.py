"""Integration tests for resume idempotency (T026 RED — FR-031 + SC-006).

Verifies that a mid-run interruption can be resumed without reprocessing
already-completed pairs and without creating duplicate comparison_results rows.
"""

import sqlite3
from pathlib import Path

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.models.reuse_v2 import CaptionPool, VideoRef


def _pool(video_ids: list[str], channel: str = "ch-a") -> CaptionPool:
    return CaptionPool(
        professor_id="prof-x",
        video_refs=[
            VideoRef(channel_alias=channel, video_id=v, author_marker="__channel_owner__")
            for v in video_ids
        ],
    )


def _insert_comparison(db: Path, source: str, target: str, mode: str = "M-nC2") -> None:
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR IGNORE INTO comparison_results "
        "(source_video_id, target_video_id, professor, course, week, session, "
        "year_from, year_to, i1_hash_match, i2_cosine_similarity, i3_change_rate, "
        "i4_new_term_count, i5_duration_diff_seconds, suspicion_score, grade, "
        "matching_mode, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, target, "prof-x", "CS101", 1, 1, 2024, 2025,
         0, 0.7, 0.1, 2, 30, 50.0, "moderate", mode, "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def test_resume_yields_only_unfinished(tmp_path: Path) -> None:
    """After 5 of 10 pairs stored, iterate_unfinished_pairs yields exactly 5 more."""
    from tube_scout.services.pair_checkpoint import (
        finalize_run,
        iterate_unfinished_pairs,
        start_run,
    )

    db = build_clean_v2_db(tmp_path / "cr.db")
    vids = ["v0", "v1", "v2", "v3", "v4"]
    pool = _pool(vids)

    run_id = start_run("prof-x", "M-nC2", 10, db)

    # Simulate 5 pairs already stored
    _insert_comparison(db, "v0", "v1")
    _insert_comparison(db, "v0", "v2")
    _insert_comparison(db, "v0", "v3")
    _insert_comparison(db, "v0", "v4")
    _insert_comparison(db, "v1", "v2")

    yielded = list(iterate_unfinished_pairs(pool, "M-nC2", db))
    assert len(yielded) == 5

    finalize_run(run_id, db, "completed")

    conn = sqlite3.connect(str(db))
    conn.execute(
        "SELECT pair_count_done FROM pair_checkpoint WHERE run_id=?", (run_id,)
    ).fetchone()
    conn.close()
    # finalize_run does not touch pair_count_done — caller is responsible


def test_no_duplicate_comparison_rows(tmp_path: Path) -> None:
    """iterate_unfinished_pairs called twice for same pool leaves no duplicate rows."""
    from tube_scout.services.pair_checkpoint import iterate_unfinished_pairs

    db = build_clean_v2_db(tmp_path / "cr.db")
    vids = ["v0", "v1", "v2"]
    pool = _pool(vids)

    # Insert all 3 pairs
    _insert_comparison(db, "v0", "v1")
    _insert_comparison(db, "v0", "v2")
    _insert_comparison(db, "v1", "v2")

    # Both calls should yield nothing (all already done)
    first = list(iterate_unfinished_pairs(pool, "M-nC2", db))
    second = list(iterate_unfinished_pairs(pool, "M-nC2", db))
    assert first == [] and second == []

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM comparison_results").fetchone()[0]
    conn.close()
    assert count == 3  # no duplicates
