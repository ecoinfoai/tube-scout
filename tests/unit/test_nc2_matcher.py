"""Unit tests for nc2_matcher service (T021 RED).

Tests verify nC2 pair generation, cosine cull filtering, empty-pool
handling, and boundary B-2 (embeddings.parquet read-only, not recomputed).
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db


def _setup_db_with_videos(
    tmp_path: Path,
    professor_id: str,
    channel_alias: str,
    video_ids: list[str],
    status: str = "fingerprinted",
) -> Path:
    db_path = build_clean_v2_db(tmp_path / "cr.db")
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) VALUES (?, ?, ?, ?)",
        (professor_id, "Test Prof", "2026-01-01", "test"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool_membership "
        "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (professor_id, channel_alias, "__channel_owner__", "2026-01-01", "test"),
    )
    for i, vid in enumerate(video_ids):
        conn.execute(
            "INSERT OR IGNORE INTO processing_status (video_id, channel_id, status, updated_at) VALUES (?, ?, ?, ?)",
            (vid, channel_alias, status, "2026-01-01"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO fingerprint_hashes (video_id, sha256_hash, full_text_length, embedding_row_index, created_at) VALUES (?, ?, ?, ?, ?)",
            (vid, f"hash{i:060x}", 1000, i, "2026-01-01"),
        )
    conn.commit()
    conn.close()
    return db_path


def _write_embeddings(captions_dir: Path, video_ids: list[str], dim: int = 8) -> Path:
    """Write a synthetic embeddings.parquet with distinct unit vectors."""
    import random

    captions_dir.mkdir(parents=True, exist_ok=True)
    emb_path = captions_dir / "embeddings.parquet"
    rng = random.Random(42)
    rows = []
    for _ in video_ids:
        v = [rng.gauss(0, 1) for _ in range(dim)]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        rows.append([x / norm for x in v])
    df = pl.DataFrame({"video_id": video_ids, "embedding": rows})
    df.write_parquet(emb_path)
    return emb_path


def test_pair_count_nc2(tmp_path: Path) -> None:
    """5-video pool with threshold=0.0 produces exactly 10 pairs (5C2)."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    vids = [f"v{i}" for i in range(5)]
    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", vids)
    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids)

    pairs = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    assert len(pairs) == 10


def test_cosine_cull_threshold(tmp_path: Path) -> None:
    """threshold=0.99 filters out low-cosine pairs."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    vids = [f"v{i}" for i in range(5)]
    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", vids)
    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids)

    # Very high threshold should filter most random-vector pairs
    pairs_high = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.99)
    pairs_none = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    # high threshold must keep fewer pairs than no threshold
    assert len(pairs_high) < len(pairs_none)


def test_empty_pool_returns_empty(tmp_path: Path) -> None:
    """Professor with 0 videos returns empty list."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", [])
    captions_dir = tmp_path / "captions"
    captions_dir.mkdir(parents=True)

    pairs = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    assert pairs == []


def test_single_video_pool_returns_empty(tmp_path: Path) -> None:
    """1-video pool (nC2=0 pairs) returns empty list."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", ["solo-vid"])
    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, ["solo-vid"])

    pairs = generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    assert pairs == []


def test_no_mapped_videos_raises(tmp_path: Path) -> None:
    """Professor with mapping but 0 collected videos raises ValueError."""
    from tube_scout.services.nc2_matcher import get_caption_pool

    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", [])
    # Empty pool: no processing_status rows
    with pytest.raises(ValueError) as exc_info:
        get_caption_pool("prof-x", db)
    assert "prof-x" in str(exc_info.value)
    assert "mapped videos" in str(exc_info.value).lower() or "caption" in str(exc_info.value).lower()


def test_loads_existing_embeddings_only(tmp_path: Path) -> None:
    """RuntimeError raised when embeddings.parquet is missing."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs

    vids = ["v0", "v1", "v2"]
    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", vids)
    captions_dir = tmp_path / "captions"
    captions_dir.mkdir(parents=True)
    # No embeddings.parquet written

    with pytest.raises(RuntimeError) as exc_info:
        generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)
    msg = str(exc_info.value)
    assert "fingerprint" in msg.lower() or "embeddings" in msg.lower()


def test_does_not_recompute_embeddings(tmp_path: Path) -> None:
    """embeddings.parquet is read exactly once per call (boundary B-2)."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs
    from tube_scout.storage import parquet_store

    vids = [f"v{i}" for i in range(4)]
    db = _setup_db_with_videos(tmp_path, "prof-x", "ch-a", vids)
    captions_dir = tmp_path / "captions"
    _write_embeddings(captions_dir, vids)

    read_calls: list[Path] = []
    original_read = parquet_store.read_parquet

    def tracking_read(filepath: Path):
        read_calls.append(filepath)
        return original_read(filepath)

    with patch.object(parquet_store, "read_parquet", side_effect=tracking_read):
        generate_nc2_pairs("prof-x", db, captions_dir, cosine_cull_threshold=0.0)

    emb_reads = [p for p in read_calls if "embeddings" in str(p)]
    assert len(emb_reads) == 1, (
        f"Expected exactly 1 embeddings.parquet read, got {len(emb_reads)}"
    )
