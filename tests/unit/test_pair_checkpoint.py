"""Unit tests for pair_checkpoint service (T022 RED).

Tests verify run lifecycle management: start, iterate (skip existing),
mark done, finalize, and resume after simulated crash (FR-031).
"""

import sqlite3
from pathlib import Path

import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.models.reuse_v2 import CaptionPool, VideoRef


def _db(tmp_path: Path) -> Path:
    return build_clean_v2_db(tmp_path / "cp.db")


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


def test_start_run_inserts_row(tmp_path: Path) -> None:
    """start_run inserts a pair_checkpoint row and returns a run_id string."""
    from tube_scout.services.pair_checkpoint import start_run

    db = _db(tmp_path)
    run_id = start_run("prof-x", "M-nC2", 10, db)
    assert isinstance(run_id, str) and len(run_id) > 0

    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT professor_id, matching_mode, pair_count_total, status "
        "FROM pair_checkpoint WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "prof-x"
    assert row[1] == "M-nC2"
    assert row[2] == 10
    assert row[3] == "in_progress"


def test_iterate_skips_existing_pairs(tmp_path: Path) -> None:
    """iterate_unfinished_pairs skips pairs already in comparison_results."""
    from tube_scout.services.pair_checkpoint import iterate_unfinished_pairs

    db = _db(tmp_path)
    vids = ["v0", "v1", "v2"]
    pool = _pool(vids)
    # Pre-insert one pair
    _insert_comparison(db, "v0", "v1")

    yielded = list(iterate_unfinished_pairs(pool, "M-nC2", db))
    yielded_pairs = {(p.source_video_id, p.target_video_id) for p in yielded}
    assert ("v0", "v1") not in yielded_pairs
    assert len(yielded) == 2  # 3C2=3 total, 1 skipped


def test_mark_pair_done_increments(tmp_path: Path) -> None:
    """mark_pair_done increments pair_count_done by 1."""
    from tube_scout.services.pair_checkpoint import mark_pair_done, start_run

    db = _db(tmp_path)
    run_id = start_run("prof-x", "M-nC2", 5, db)
    mark_pair_done(run_id, db)
    mark_pair_done(run_id, db)

    conn = sqlite3.connect(str(db))
    count = conn.execute(
        "SELECT pair_count_done FROM pair_checkpoint WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    conn.close()
    assert count == 2


def test_finalize_sets_status(tmp_path: Path) -> None:
    """finalize_run sets status to 'completed' or 'aborted'."""
    from tube_scout.services.pair_checkpoint import finalize_run, start_run

    db = _db(tmp_path)
    run_id = start_run("prof-x", "M-nC2", 5, db)
    checkpoint = finalize_run(run_id, db, "completed")
    assert checkpoint.status == "completed"
    assert checkpoint.run_id == run_id

    db2 = _db(tmp_path / "b")
    run_id2 = start_run("prof-x", "M-nC2", 5, db2)
    cp2 = finalize_run(run_id2, db2, "aborted")
    assert cp2.status == "aborted"


def test_resume_after_simulated_crash(tmp_path: Path) -> None:
    """After crash (in_progress), new iterate yields only unfinished pairs."""
    from tube_scout.services.pair_checkpoint import iterate_unfinished_pairs, start_run

    db = _db(tmp_path)
    vids = ["v0", "v1", "v2", "v3", "v4"]
    pool = _pool(vids)

    start_run("prof-x", "M-nC2", 10, db)
    # Simulate 5 of 10 pairs already stored in comparison_results
    _insert_comparison(db, "v0", "v1")
    _insert_comparison(db, "v0", "v2")
    _insert_comparison(db, "v0", "v3")
    _insert_comparison(db, "v0", "v4")
    _insert_comparison(db, "v1", "v2")

    yielded = list(iterate_unfinished_pairs(pool, "M-nC2", db))
    assert len(yielded) == 5  # 10 - 5 already done


def test_resume_run_returns_none_when_no_in_progress(tmp_path: Path) -> None:
    """resume_run returns None when no in_progress run exists for professor."""
    from tube_scout.services.pair_checkpoint import resume_run

    db = _db(tmp_path)
    result = resume_run("prof-new", "M-nC2", db)
    assert result is None


def test_resume_run_finds_in_progress(tmp_path: Path) -> None:
    """resume_run returns the run_id of an existing in_progress run."""
    from tube_scout.services.pair_checkpoint import resume_run, start_run

    db = _db(tmp_path)
    run_id = start_run("prof-x", "M-nC2", 10, db)
    found = resume_run("prof-x", "M-nC2", db)
    assert found == run_id
