"""nC2 candidate pair generator for spec 011 cross-channel reuse detection.

Generates all unordered video pairs (nC2) for a professor's caption pool
after a cheap cosine-similarity pre-filter (R-1). Never recomputes
embeddings — reads embeddings.parquet produced by spec 007 fingerprint
(boundary B-2).
"""

import sqlite3
from itertools import combinations
from pathlib import Path

import polars as pl

from tube_scout.models.reuse_v2 import CandidatePair, CaptionPool
from tube_scout.services.professor_resolver import resolve_caption_pool
from tube_scout.storage import parquet_store


def get_caption_pool(professor_id: str, db_path: Path) -> CaptionPool:
    """Resolve all video refs for a professor across mapped channels.

    Calls professor_resolver.resolve_caption_pool then filters to only
    videos with status 'fingerprinted', 'collected', or 'compared' in
    processing_status. Raises if the resulting pool is empty.

    Args:
        professor_id: Identifier registered in professor_pool.
        db_path: Path to content_reuse.db SQLite file.

    Returns:
        CaptionPool containing all collectible video refs.

    Raises:
        TypeError: If db_path is not a Path.
        ValueError: If professor has no mapped videos with collected captions.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    pool = resolve_caption_pool(professor_id, db_path)

    if not pool.video_refs:
        raise ValueError(
            f"Professor '{professor_id}' has no mapped videos with collected captions. "
            f"Verify mapping and caption availability."
        )

    return pool


def generate_nc2_pairs(
    professor_id: str,
    db_path: Path,
    captions_dir: Path,
    cosine_cull_threshold: float,
) -> list[CandidatePair]:
    """Generate nC2 candidate pairs for a single professor's caption pool.

    Performs cheap I-2 cosine cull before returning candidates so that
    downstream segment alignment is bounded.

    Steps:
      1. Load CaptionPool via get_caption_pool.
      2. Read embeddings.parquet (spec 007 boundary B-2 — read-only).
      3. Compute pairwise cosine via numpy matrix op.
      4. Filter pairs below cosine_cull_threshold.
      5. Return list[CandidatePair].

    Pool size N → at most N*(N-1)/2 pairs before cull.

    Args:
        professor_id: Identifier registered in professor_pool.
        db_path: Path to content_reuse.db SQLite file.
        captions_dir: Directory containing embeddings.parquet (spec 010 output).
        cosine_cull_threshold: Pairs with cosine < threshold are dropped.

    Returns:
        List of CandidatePair with source_video_id, target_video_id, cosine.

    Raises:
        TypeError: If db_path or captions_dir is not a Path.
        ValueError: If the professor pool is empty.
        RuntimeError: If embeddings.parquet is missing — run fingerprint first.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")
    if not isinstance(captions_dir, Path):
        raise TypeError(f"captions_dir must be a Path, got {type(captions_dir).__name__}")

    try:
        pool = get_caption_pool(professor_id, db_path)
    except ValueError:
        return []

    video_ids = [vr.video_id for vr in pool.video_refs]

    if len(video_ids) < 2:
        return []

    emb_path = captions_dir / "embeddings.parquet"
    emb_df = parquet_store.read_parquet(emb_path)
    if emb_df is None:
        raise RuntimeError(
            f"embeddings.parquet not found at '{emb_path}'. "
            f"Run 'tube-scout content fingerprint --project <project>' first."
        )

    # Filter to only rows in the professor's pool, preserving order
    video_id_set = set(video_ids)
    emb_df = emb_df.filter(pl.col("video_id").is_in(list(video_id_set)))

    if emb_df.is_empty() or len(emb_df) < 2:
        return []

    ordered_ids = emb_df["video_id"].to_list()
    raw_vecs: list[list[float]] = emb_df["embedding"].to_list()

    # Normalize each vector using polars-compatible math (no numpy dependency)
    def _normalize(v: list[float]) -> list[float]:
        norm = sum(x * x for x in v) ** 0.5
        if norm == 0.0:
            return v
        return [x / norm for x in v]

    vecs = [_normalize(v) for v in raw_vecs]

    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    pairs: list[CandidatePair] = []
    n = len(ordered_ids)
    for i, j in combinations(range(n), 2):
        cosine = min(1.0, max(0.0, _dot(vecs[i], vecs[j])))
        if cosine >= cosine_cull_threshold:
            pairs.append(
                CandidatePair(
                    source_video_id=ordered_ids[i],
                    target_video_id=ordered_ids[j],
                    cosine=cosine,
                    professor_id=professor_id,
                )
            )

    return pairs
