"""T069 RED — nC2 resume integration test (spec 013 T069).

Tests that run_nc2_analysis with resume=True skips already-analyzed pairs
and produces a final result identical to an uninterrupted run.

Setup: 9-video pool → 36 pairs.
Phase 1: Run analysis for first 10 pairs only (simulate partial run).
Phase 2: Resume with resume=True → remaining pairs analyzed.
Assert: total comparison_results = 36, no duplicates.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

VIDEO_IDS = [
    "res_vid_aaa",
    "res_vid_bbb",
    "res_vid_ccc",
    "res_vid_ddd",
    "res_vid_eee",
    "res_vid_fff",
    "res_vid_ggg",
    "res_vid_hhh",
    "res_vid_iii",
]
EXPECTED_PAIRS = len(VIDEO_IDS) * (len(VIDEO_IDS) - 1) // 2  # 36


def _setup_resume_db(tmp_path: Path, professor: str = "prof-resume") -> Path:
    db_path = tmp_path / "content_reuse_resume.db"

    from tube_scout.storage.content_db import ContentDB, migrate_to_v2, migrate_to_v3, _ensure_v4
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata "
            "(channel_id, channel_alias, title, source, ingested_at) VALUES (?, ?, ?, ?, ?)",
            ("UCresume0000000001", "resume_ch", "Resume Channel", "takeout", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
            (professor, "Resume Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor, "resume_ch", "__channel_owner__", "2026-01-01T00:00:00+00:00", "test"),
        )
        for vid_id in VIDEO_IDS:
            conn.execute(
                "INSERT OR IGNORE INTO video_metadata "
                "(video_id, channel_id, title, duration_seconds, source, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vid_id, "UCresume0000000001", f"Video {vid_id}", 1800.0, "takeout", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO processing_status "
                "(video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
                (vid_id, "UCresume0000000001", "collected", "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()

    return db_path


def test_resume_completes_partial_run(tmp_path: Path) -> None:
    """resume=True: re-run after partial analysis reaches exactly 36 total pairs."""
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB
    from itertools import combinations

    professor = "prof-resume"
    db_path = _setup_resume_db(tmp_path, professor)

    # Phase 1: manually insert 10 comparison_results to simulate partial run
    sorted_ids = sorted(VIDEO_IDS)
    all_pairs = list(combinations(sorted_ids, 2))
    first_10_pairs = all_pairs[:10]

    now_iso = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        for src, tgt in first_10_pairs:
            conn.execute(
                "INSERT OR IGNORE INTO comparison_results "
                "(source_video_id, target_video_id, professor, professor_id, "
                "course, week, session, year_from, year_to, matching_mode, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (src, tgt, professor, professor, "", 0, 0, 0, 0, "M-nC2", now_iso),
            )
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        count_after_phase1 = conn.execute("SELECT COUNT(*) FROM comparison_results").fetchone()[0]

    assert count_after_phase1 == 10, f"Phase 1: expected 10 rows, got {count_after_phase1}"

    # Phase 2: resume run
    db = ContentDB(db_path)
    try:
        result2 = run_nc2_analysis(
            professor=professor,
            channel_alias="resume_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
            resume=True,
        )
    finally:
        db.close()

    with sqlite3.connect(db_path) as conn:
        count_final = conn.execute("SELECT COUNT(*) FROM comparison_results").fetchone()[0]

    assert count_final == EXPECTED_PAIRS, (
        f"After resume, expected {EXPECTED_PAIRS} total rows, got {count_final}"
    )
    assert result2.pairs_analyzed <= EXPECTED_PAIRS - 10, (
        f"resume=True must skip 10 existing pairs; pairs_analyzed={result2.pairs_analyzed} "
        f"but max expected {EXPECTED_PAIRS - 10}"
    )


def test_resume_no_duplicate_rows(tmp_path: Path) -> None:
    """Running run_nc2_analysis twice without resume does not create duplicates.

    This test is RED until run_nc2_analysis uses INSERT OR IGNORE correctly.
    """
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB

    professor = "prof-resume"
    db_path = _setup_resume_db(tmp_path, professor)

    db = ContentDB(db_path)
    try:
        run_nc2_analysis(
            professor=professor,
            channel_alias="resume_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
        run_nc2_analysis(
            professor=professor,
            channel_alias="resume_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
    finally:
        db.close()

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM comparison_results").fetchone()[0]

    assert count == EXPECTED_PAIRS, (
        f"Two runs must not create duplicates: expected {EXPECTED_PAIRS}, got {count}"
    )


def test_pair_checkpoint_updated_on_completion(tmp_path: Path) -> None:
    """pair_checkpoint table is updated after run_nc2_analysis completes.

    This test is RED until run_nc2_analysis writes pair_checkpoint rows.
    """
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB

    professor = "prof-resume"
    db_path = _setup_resume_db(tmp_path, professor)

    db = ContentDB(db_path)
    try:
        run_nc2_analysis(
            professor=professor,
            channel_alias="resume_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
    finally:
        db.close()

    with sqlite3.connect(db_path) as conn:
        checkpoint_count = conn.execute(
            "SELECT COUNT(*) FROM pair_checkpoint WHERE professor_id = ?", (professor,)
        ).fetchone()[0]

    assert checkpoint_count > 0, (
        f"Expected pair_checkpoint row for professor '{professor}' after analysis, "
        "but got 0 rows. run_nc2_analysis must write to pair_checkpoint."
    )
