"""Integration tests for cross-channel pool resolution (T024 RED — boundary B-1).

Verifies that a professor mapped to multiple channels gets a unified
CaptionPool including videos from all channels, and that nC2 pairs
include cross-channel combinations.
"""

import sqlite3
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db
from tube_scout.services.professor_resolver import map_professor, resolve_caption_pool


def _insert_videos(db: Path, channel: str, video_ids: list[str]) -> None:
    conn = sqlite3.connect(str(db))
    for i, vid in enumerate(video_ids):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (vid, channel, "fingerprinted", "2026-01-01"),
        )
    conn.commit()
    conn.close()


def _write_embeddings(captions_dir: Path, video_ids: list[str], dim: int = 8) -> None:
    import numpy as np

    captions_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    vecs = rng.random((len(video_ids), dim)).astype("float32")
    norms = vecs.sum(axis=1, keepdims=True)
    vecs = vecs / norms
    df = pl.DataFrame({"video_id": video_ids, "embedding": vecs.tolist()})
    df.write_parquet(captions_dir / "embeddings.parquet")


def test_cross_channel_pool_contains_both_channels(tmp_path: Path) -> None:
    """CaptionPool from 2-channel mapping contains video_refs from both channels."""
    db = build_clean_v2_db(tmp_path / "cr.db")
    map_professor("prof-x", "Prof X", "alias_a", "__channel_owner__", db, "test")
    map_professor("prof-x", "Prof X", "alias_b", "__channel_owner__", db, "test")

    _insert_videos(db, "alias_a", ["a1", "a2", "a3"])
    _insert_videos(db, "alias_b", ["b1", "b2", "b3"])

    pool = resolve_caption_pool("prof-x", db)
    assert len(pool.video_refs) == 6
    aliases = {vr.channel_alias for vr in pool.video_refs}
    assert "alias_a" in aliases
    assert "alias_b" in aliases


def test_nc2_includes_cross_channel_pairs(tmp_path: Path) -> None:
    """nC2 candidate pairs include cross-channel combinations (B-1)."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    db = build_clean_v2_db(tmp_path / "cr.db")
    map_professor("prof-x", "Prof X", "alias_a", "__channel_owner__", db, "test")
    map_professor("prof-x", "Prof X", "alias_b", "__channel_owner__", db, "test")

    vids_a = ["a1", "a2"]
    vids_b = ["b1", "b2"]
    _insert_videos(db, "alias_a", vids_a)
    _insert_videos(db, "alias_b", vids_b)

    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids_a + vids_b)

    pairs = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    assert len(pairs) == 6  # 4C2 = 6

    pair_set = {(p.source_video_id, p.target_video_id) for p in pairs}
    pair_set |= {(p.target_video_id, p.source_video_id) for p in pairs}
    # At least one cross-channel pair exists
    cross_channel = any(
        (src in vids_a and tgt in vids_b) or (src in vids_b and tgt in vids_a)
        for src, tgt in pair_set
    )
    assert cross_channel, "No cross-channel pair found (boundary B-1 violation)"
