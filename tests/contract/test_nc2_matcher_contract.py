"""T059 RED — contract tests for nc2_matcher (spec 013 section A + E).

Verifies the contract-specified signatures:
  generate_nc2_pairs(professor, db, *, layer_a_min_seconds) -> Iterator[VideoPairRef]
  run_nc2_analysis(professor, channel_alias, db, ...) -> AnalysisResult
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


# ─── helpers ─────────────────────────────────────────────────────────────────

def _setup_db(tmp_path: Path, professor: str = "prof-park") -> Path:
    """Create a minimal v4 DB with professor_pool + video_metadata rows."""
    db_path = tmp_path / "content_reuse.db"

    from tube_scout.storage.content_db import ContentDB, migrate_to_v2, migrate_to_v3, _ensure_v4
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    with sqlite3.connect(db_path) as conn:
        # channel_metadata required by FK
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata "
            "(channel_id, channel_alias, title, source, ingested_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("UCtest000000000001", "test_ch", "Test Channel", "takeout", "2026-01-01T00:00:00+00:00"),
        )
        # professor_pool
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (professor, "Park Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        # membership
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor, "test_ch", "__channel_owner__", "2026-01-01T00:00:00+00:00", "test"),
        )
        # 4 videos (≥30 s duration so layer A does not cull them all)
        videos = [
            ("vid_aaa", "UCtest000000000001", "Video A", 1800.0, "2026-01-01T00:00:00+00:00"),
            ("vid_bbb", "UCtest000000000001", "Video B", 1800.0, "2026-01-01T00:00:00+00:00"),
            ("vid_ccc", "UCtest000000000001", "Video C", 1800.0, "2026-01-01T00:00:00+00:00"),
            ("vid_ddd", "UCtest000000000001", "Video D", 1800.0, "2026-01-01T00:00:00+00:00"),
        ]
        for vid_id, ch_id, title, dur, ingested_at in videos:
            conn.execute(
                "INSERT OR IGNORE INTO video_metadata "
                "(video_id, channel_id, title, duration_seconds, source, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vid_id, ch_id, title, dur, "takeout", ingested_at),
            )
            conn.execute(
                "INSERT OR IGNORE INTO processing_status "
                "(video_id, channel_id, status, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (vid_id, ch_id, "collected", "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()

    return db_path


def _setup_db_with_short_video(tmp_path: Path, professor: str = "prof-short") -> Path:
    """Create a DB where one video is very short (< 30 s) — Layer A should cull it."""
    db_path = tmp_path / "content_reuse_short.db"

    from tube_scout.storage.content_db import ContentDB, migrate_to_v2, migrate_to_v3, _ensure_v4
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata "
            "(channel_id, channel_alias, title, source, ingested_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("UCtest000000000002", "test_ch2", "Short Channel", "takeout", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) "
            "VALUES (?, ?, ?, ?)",
            (professor, "Short Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor, "test_ch2", "__channel_owner__", "2026-01-01T00:00:00+00:00", "test"),
        )
        # 3 videos: 2 long, 1 short
        videos = [
            ("vid_long1", "UCtest000000000002", "Long 1", 1800.0),
            ("vid_long2", "UCtest000000000002", "Long 2", 1800.0),
            ("vid_short", "UCtest000000000002", "Short", 10.0),   # below 30 s threshold
        ]
        for vid_id, ch_id, title, dur in videos:
            conn.execute(
                "INSERT OR IGNORE INTO video_metadata "
                "(video_id, channel_id, title, duration_seconds, source, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vid_id, ch_id, title, dur, "takeout", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO processing_status "
                "(video_id, channel_id, status, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (vid_id, ch_id, "collected", "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()

    return db_path


# ─── contract tests ───────────────────────────────────────────────────────────


def test_generate_nc2_pairs_returns_n_choose_2(tmp_path: Path) -> None:
    """4 videos in pool → C(4,2) = 6 pairs yielded (no Layer A cull)."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.storage.content_db import ContentDB

    professor = "prof-park"
    db_path = _setup_db(tmp_path, professor)
    db = ContentDB(db_path)
    try:
        pairs = list(generate_nc2_pairs(professor, db, layer_a_min_seconds=30.0))
    finally:
        db.close()

    assert len(pairs) == 6, f"C(4,2) = 6 expected, got {len(pairs)}"

    # All pairs must be ordered (source < target lexicographically)
    for pair in pairs:
        assert pair.source_video_id < pair.target_video_id, (
            f"Pairs must be lexicographically ordered: "
            f"got source={pair.source_video_id!r}, target={pair.target_video_id!r}"
        )


def test_generate_nc2_pairs_skips_layer_a_short(tmp_path: Path) -> None:
    """One short video (10 s) → pairs containing it are culled by Layer A.

    3 videos: 2 long + 1 short.
    Without cull: C(3,2) = 3 pairs.
    With Layer A (min_seconds=30): 2 pairs involving short video are culled.
    Remaining: 1 pair (long1, long2).
    """
    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.storage.content_db import ContentDB

    professor = "prof-short"
    db_path = _setup_db_with_short_video(tmp_path, professor)
    db = ContentDB(db_path)
    try:
        pairs = list(generate_nc2_pairs(professor, db, layer_a_min_seconds=30.0))
    finally:
        db.close()

    assert len(pairs) == 1, (
        f"Expected 1 pair after Layer A cull (short video removed), got {len(pairs)}: "
        f"{[(p.source_video_id, p.target_video_id) for p in pairs]}"
    )
    pair = pairs[0]
    assert "vid_short" not in (pair.source_video_id, pair.target_video_id), (
        "Short video must not appear in any yielded pair"
    )


def test_run_nc2_analysis_resumable_via_checkpoint(tmp_path: Path) -> None:
    """run_nc2_analysis with resume=True: completed pairs not re-analyzed.

    Setup: 4 videos → 6 pairs. Mark 2 pairs as already completed in
    pair_checkpoint. With resume=True, only 4 pairs should be analyzed.
    """
    from tube_scout.services.nc2_matcher import run_nc2_analysis, AnalysisResult
    from tube_scout.storage.content_db import ContentDB

    professor = "prof-park"
    db_path = _setup_db(tmp_path, professor)
    db = ContentDB(db_path)

    # Pre-populate pair_checkpoint with 2 pairs already done
    run_id = "nc2-test-run-001"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pair_checkpoint "
            "(run_id, professor_id, matching_mode, pair_count_total, pair_count_done, "
            "started_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, professor, "M-nC2", 6, 2, "2026-01-01T00:00:00+00:00", "in_progress"),
        )
        # Mark vid_aaa↔vid_bbb and vid_aaa↔vid_ccc as analyzed
        for src, tgt in [("vid_aaa", "vid_bbb"), ("vid_aaa", "vid_ccc")]:
            conn.execute(
                "INSERT OR IGNORE INTO comparison_results "
                "(source_video_id, target_video_id, professor, course, week, session, "
                "year_from, year_to, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (src, tgt, professor, "Test Course", 1, 1, 2025, 2026,
                 "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()

    try:
        result = run_nc2_analysis(
            professor=professor,
            channel_alias="test_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
            resume=True,
        )
    finally:
        db.close()

    assert isinstance(result, AnalysisResult), (
        f"Expected AnalysisResult, got {type(result)}"
    )
    assert result.professor == professor
    assert result.matching_mode == "M-nC2"
    assert result.total_pairs_generated == 6, (
        f"Total pairs (pre-resume) must be 6, got {result.total_pairs_generated}"
    )
    # With 2 already done and resume=True, at most 4 pairs analyzed
    assert result.pairs_analyzed <= 4, (
        f"With resume=True and 2 done, pairs_analyzed must be ≤ 4, got {result.pairs_analyzed}"
    )
