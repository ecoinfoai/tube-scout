"""T067 RED — nC2 full integration test with source_type_pair + audio_fp assertions.

Runs run_nc2_analysis on 9-video fixture (mock transcripts + mock audio fp).
Verifies:
  - comparison_results 36 rows (C(9,2))
  - Every row has non-NULL audio_fp_hamming, audio_fp_best_offset, audio_fp_overlap_seconds
  - source_type_pair ∈ {asr-asr, api-api, asr-api, manual-asr} (FR-026)
  - At least 2 distinct values of source_type_pair (mixed-source pair coverage)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

FIXTURE_TAKEOUT = Path(__file__).parent.parent / "fixtures" / "takeout_sample" / "Takeout"
VIDEO_IDS = [
    "aaaaaaaaaaa",
    "bbbbbbbbbbb",
    "ccccccccccc",
    "ddddddddddd",
    "eeeeeeeeeee",
    "fffffffffff",
    "ggggggggggg",
    "hhhhhhhhhhh",
    "iiiiiiiiiii",
]
EXPECTED_PAIRS = len(VIDEO_IDS) * (len(VIDEO_IDS) - 1) // 2  # C(9,2) = 36


def _setup_v4_db_with_videos(tmp_path: Path) -> Path:
    """Create v4 DB with 9 videos and professor pool."""
    db_path = tmp_path / "content_reuse.db"

    from tube_scout.storage.content_db import ContentDB, migrate_to_v2, migrate_to_v3, _ensure_v4
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    professor = "prof-test"
    channel_alias = "test_ch"
    channel_id = "UCtest000000000001"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata "
            "(channel_id, channel_alias, title, source, ingested_at) VALUES (?, ?, ?, ?, ?)",
            (channel_id, channel_alias, "Test Channel", "takeout", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool "
            "(professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
            (professor, "Test Prof", "2026-01-01T00:00:00+00:00", "test"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO professor_pool_membership "
            "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (professor, channel_alias, "__channel_owner__", "2026-01-01T00:00:00+00:00", "test"),
        )
        for i, vid_id in enumerate(VIDEO_IDS):
            conn.execute(
                "INSERT OR IGNORE INTO video_metadata "
                "(video_id, channel_id, title, duration_seconds, source, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (vid_id, channel_id, f"Video {i}", 1800.0, "takeout", "2026-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO processing_status "
                "(video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
                (vid_id, channel_id, "collected", "2026-01-01T00:00:00+00:00"),
            )
        # Assign caption_source_detail for mixed-source testing
        # First 5 videos: asr, last 4: transcript_api
        for i, vid_id in enumerate(VIDEO_IDS):
            source = "whisper" if i < 5 else "transcript_api"
            conn.execute(
                "UPDATE processing_status SET caption_source = ? WHERE video_id = ?",
                (source, vid_id),
            )
        conn.commit()

    return db_path


def test_nc2_full_36_pairs(tmp_path: Path) -> None:
    """run_nc2_analysis produces 36 comparison_results rows for 9 videos."""
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB

    db_path = _setup_v4_db_with_videos(tmp_path)
    db = ContentDB(db_path)
    try:
        result = run_nc2_analysis(
            professor="prof-test",
            channel_alias="test_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
    finally:
        db.close()

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM comparison_results").fetchone()[0]

    assert result.total_pairs_generated == EXPECTED_PAIRS, (
        f"Expected {EXPECTED_PAIRS} pairs, got {result.total_pairs_generated}"
    )
    assert count == EXPECTED_PAIRS, (
        f"Expected {EXPECTED_PAIRS} comparison_results rows, got {count}"
    )


def test_nc2_audio_fp_columns_non_null(tmp_path: Path) -> None:
    """FR-032: audio_fp_hamming, audio_fp_best_offset, audio_fp_overlap_seconds non-NULL.

    This test is RED until run_nc2_analysis populates these columns.
    """
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB

    db_path = _setup_v4_db_with_videos(tmp_path)
    db = ContentDB(db_path)
    try:
        run_nc2_analysis(
            professor="prof-test",
            channel_alias="test_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
    finally:
        db.close()

    with sqlite3.connect(db_path) as conn:
        null_hamming = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE audio_fp_hamming IS NULL"
        ).fetchone()[0]
        null_offset = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE audio_fp_best_offset IS NULL"
        ).fetchone()[0]
        null_overlap = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE audio_fp_overlap_seconds IS NULL"
        ).fetchone()[0]

    assert null_hamming == 0, (
        f"FR-032: {null_hamming} rows have NULL audio_fp_hamming (expected 0)"
    )
    assert null_offset == 0, (
        f"FR-032: {null_offset} rows have NULL audio_fp_best_offset (expected 0)"
    )
    assert null_overlap == 0, (
        f"FR-032: {null_overlap} rows have NULL audio_fp_overlap_seconds (expected 0)"
    )


def test_nc2_source_type_pair_values(tmp_path: Path) -> None:
    """FR-026: source_type_pair set correctly for mixed asr/api sources.

    With 5 asr + 4 api videos, expect asr-asr, api-api, asr-api pairs.
    This test is RED until run_nc2_analysis populates source_type_pair.
    """
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB

    db_path = _setup_v4_db_with_videos(tmp_path)
    db = ContentDB(db_path)
    try:
        run_nc2_analysis(
            professor="prof-test",
            channel_alias="test_ch",
            db=db,
            matching_mode="M-nC2",
            layer_a_min_seconds=30.0,
        )
    finally:
        db.close()

    valid_source_pairs = {"asr-asr", "api-api", "asr-api", "manual-asr"}

    with sqlite3.connect(db_path) as conn:
        null_stp = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE source_type_pair IS NULL"
        ).fetchone()[0]
        distinct_stp = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT source_type_pair FROM comparison_results WHERE source_type_pair IS NOT NULL"
            ).fetchall()
        }

    assert null_stp == 0, (
        f"FR-026: {null_stp} rows have NULL source_type_pair (expected 0)"
    )
    invalid = distinct_stp - valid_source_pairs
    assert not invalid, f"FR-026: invalid source_type_pair values: {invalid}"
    assert len(distinct_stp) >= 2, (
        f"FR-026: expected >= 2 distinct source_type_pair values, got {distinct_stp}"
    )
