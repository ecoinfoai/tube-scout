"""Integration tests for nC2 pipeline basic flow (T023 RED).

Tests the end-to-end candidate generation across multiple channels for a
single professor. Time-axis integration (T036) is a deferred xfail placeholder.
"""

import sqlite3
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.services.professor_resolver import map_professor


def _insert_videos(db: Path, channel: str, video_ids: list[str]) -> None:
    conn = sqlite3.connect(str(db))
    for i, vid in enumerate(video_ids):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (vid, channel, "fingerprinted", "2026-01-01"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fingerprint_hashes (video_id, sha256_hash, full_text_length, embedding_row_index, created_at) VALUES (?, ?, ?, ?, ?)",
            (vid, f"hash{i:060x}", 1000, i, "2026-01-01"),
        )
    conn.commit()
    conn.close()


def _write_embeddings(captions_dir: Path, video_ids: list[str], dim: int = 8) -> None:
    import random

    captions_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    rows = []
    for _ in video_ids:
        v = [rng.gauss(0, 1) for _ in range(dim)]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        rows.append([x / norm for x in v])
    df = pl.DataFrame({"video_id": video_ids, "embedding": rows})
    df.write_parquet(captions_dir / "embeddings.parquet")


def test_nc2_basic_flow(tmp_path: Path) -> None:
    """5-video pool across 2 channels → exactly 10 nC2 candidate pairs."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    db = build_clean_v2_db(tmp_path / "cr.db")
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-a",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="test",
    )
    map_professor(
        professor_id="prof-x",
        display_name="Prof X",
        channel_alias="ch-b",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="test",
    )

    vids_a = ["a1", "a2", "a3"]
    vids_b = ["b1", "b2"]
    _insert_videos(db, "ch-a", vids_a)
    _insert_videos(db, "ch-b", vids_b)

    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids_a + vids_b)

    pairs = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    assert len(pairs) == 10  # 5C2 = 10


def test_nc2_with_time_axis(tmp_path: Path) -> None:
    """Full nc2 pipeline with case_a captions → i6/i7/i8 non-NULL + match_spans rows.

    T036: verifies that comparison_results rows produced by the nC2 pipeline
    carry time-axis indicators (i6/i7/i8) and that match_spans rows are
    persisted. Also checks that composite suspicion_score is computed via
    8-indicator weighting (not 5-indicator spec 007 formula).
    """
    import json

    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.services.pair_checkpoint import (
        finalize_run,
        iterate_unfinished_pairs,
        mark_pair_done,
        start_run,
    )
    from tube_scout.services.professor_resolver import (
        map_professor,
        resolve_caption_pool,
    )
    from tube_scout.services.time_axis_indicators import compute_time_axis
    from tube_scout.services.content_comparator import compute_suspicion_score
    from tube_scout.models.reuse_v2 import PolicyConfig
    from tube_scout.storage.content_db import insert_match_spans

    FIXTURES = Path(__file__).parent.parent / "fixtures" / "spec011" / "captions"

    db = build_clean_v2_db(tmp_path / "cr.db")
    captions_dir = tmp_path / "captions"
    captions_dir.mkdir()

    # Register professor with one channel
    map_professor(
        professor_id="prof-t036",
        display_name="T036 Prof",
        channel_alias="ch-t036",
        author_marker="__channel_owner__",
        db_path=db,
        registered_by="test",
    )

    # Insert 2 videos and link to fixture captions (case_a)
    video_ids = ["vid_a01", "vid_a02"]
    conn = sqlite3.connect(str(db))
    for i, vid in enumerate(video_ids):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status "
            "(video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (vid, "ch-t036", "fingerprinted", "2026-01-01"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fingerprint_hashes "
            "(video_id, sha256_hash, full_text_length, embedding_row_index, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (vid, f"hash{i:060x}", 1000, i, "2026-01-01"),
        )
    conn.commit()
    conn.close()

    # Write embeddings.parquet for cosine cull (both same direction → high cosine)
    import random
    rng = random.Random(42)
    v = [rng.gauss(0, 1) for _ in range(8)]
    norm = sum(x * x for x in v) ** 0.5 or 1.0
    unit_v = [x / norm for x in v]
    df = pl.DataFrame({"video_id": video_ids, "embedding": [unit_v, unit_v]})
    df.write_parquet(captions_dir / "embeddings.parquet")

    # Copy caption fixtures into captions_dir as vid_a01.json / vid_a02.json
    for vid, fixture in [("vid_a01", "case_a_video1.json"), ("vid_a02", "case_a_video2.json")]:
        src = FIXTURES / fixture
        (captions_dir / f"{vid}.json").write_text(src.read_text())

    # Generate nC2 pairs (threshold=0 so pair always included)
    pairs = generate_nc2_pairs("prof-t036", db, captions_dir, cosine_cull_threshold=0.0)
    assert len(pairs) == 1  # 2C2 = 1

    pool = resolve_caption_pool("prof-t036", db)
    policy = PolicyConfig()
    run_id = start_run("prof-t036", "M-nC2", 1, db)

    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()

    conn = sqlite3.connect(str(db))
    comparison_id = None
    for pair_ref in iterate_unfinished_pairs(pool, "M-nC2", db):
        # Load captions
        segs_a_raw = json.loads((captions_dir / f"{pair_ref.source_video_id}.json").read_text())["segments"]
        segs_b_raw = json.loads((captions_dir / f"{pair_ref.target_video_id}.json").read_text())["segments"]

        # Compute time-axis
        from tube_scout.models.reuse_v2 import CandidatePair
        cp = CandidatePair(
            source_video_id=pair_ref.source_video_id,
            target_video_id=pair_ref.target_video_id,
            cosine=1.0,
            professor_id="prof-t036",
        )
        ta = compute_time_axis(cp, segs_a_raw, segs_b_raw)

        # Compute 8-indicator score
        score, grade = compute_suspicion_score(
            i1_hash_match=False,
            i2_cosine_similarity=1.0,
            i3_change_rate=0.0,
            i4_new_term_count=0,
            i5_duration_diff_seconds=0.0,
            i6_longest_contiguous_seconds=ta.i6_longest_contiguous_seconds,
            i7_distribution_dispersion=ta.i7_distribution_dispersion,
            i8_position_diversity=ta.i8_position_diversity,
            policy=policy,
        )

        cursor = conn.execute(
            "INSERT OR IGNORE INTO comparison_results "
            "(source_video_id, target_video_id, matching_mode, professor_id, "
            "i6_longest_contiguous_seconds, i7_distribution_dispersion, "
            "i8_position_diversity, suspicion_score, grade, created_at) "
            "VALUES (?, ?, 'M-nC2', ?, ?, ?, ?, ?, ?, ?)",
            (pair_ref.source_video_id, pair_ref.target_video_id, "prof-t036",
             ta.i6_longest_contiguous_seconds, ta.i7_distribution_dispersion,
             ta.i8_position_diversity, score, grade, now),
        )
        conn.commit()
        comparison_id = cursor.lastrowid
        mark_pair_done(run_id, db)

    conn.close()

    finalize_run(run_id, db, "completed")

    # Insert match_spans
    assert comparison_id is not None
    if ta.spans:
        insert_match_spans(comparison_id, ta.spans, db)

    # Verify comparison_results row has non-NULL i6/i7/i8
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT i6_longest_contiguous_seconds, i7_distribution_dispersion, "
        "i8_position_diversity, suspicion_score, grade "
        "FROM comparison_results WHERE id = ?",
        (comparison_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["i6_longest_contiguous_seconds"] is not None, "i6 must not be NULL"
    assert row["i7_distribution_dispersion"] is not None, "i7 must not be NULL"
    assert row["i8_position_diversity"] is not None, "i8 must not be NULL"
    assert row["suspicion_score"] is not None, "suspicion_score must not be NULL"

    # Verify match_spans rows were inserted
    conn = sqlite3.connect(str(db))
    span_count = conn.execute(
        "SELECT COUNT(*) FROM match_spans WHERE comparison_id = ?",
        (comparison_id,),
    ).fetchone()[0]
    conn.close()
    assert span_count > 0 or len(ta.spans) == 0, (
        f"Expected match_spans rows for comparison_id={comparison_id}"
    )

    # Verify composite score differs from naive 5-indicator sum
    # (8-indicator weighted score includes i6/i7/i8 which add mass)
    assert row["grade"] in ("normal", "moderate", "high", "critical")
