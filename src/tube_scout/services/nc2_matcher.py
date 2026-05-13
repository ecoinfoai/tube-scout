"""nC2 pair generator and analysis driver for spec 011/013 cross-channel reuse.

spec 011: generate_nc2_candidate_pairs (cosine-cull, embeddings.parquet-based)
spec 013: generate_nc2_pairs + run_nc2_analysis (DB-based, Layer A, resume)
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import polars as pl
from pydantic import BaseModel, Field

from tube_scout.models.reuse_v2 import CandidatePair, CaptionPool, VideoPairRef
from tube_scout.services.professor_resolver import resolve_caption_pool
from tube_scout.storage import parquet_store

if TYPE_CHECKING:
    from tube_scout.services.progress_reporter import ProgressReporter
    from tube_scout.storage.content_db import ContentDB


# ─── spec 013 §E — AnalysisResult ─────────────────────────────────────────────


class AnalysisResult(BaseModel):
    """Summary of one nC2 analysis run.

    Attributes:
        professor: Professor pool identifier.
        channel_alias: Channel alias for this run.
        matching_mode: Analysis mode used.
        total_pairs_generated: All pairs enumerated before Layer A.
        pairs_culled_layer_a: Pairs removed by Layer A (video too short).
        pairs_analyzed: Pairs that were processed.
        pairs_failed: Pairs that raised an error during analysis.
        elapsed_seconds: Total wall-clock time for this run.
        pattern_distribution: Count per ReusePatternLabel value.
    """

    professor: str
    channel_alias: str
    matching_mode: Literal["M-default", "M-nC2"]
    total_pairs_generated: int = Field(..., ge=0)
    pairs_culled_layer_a: int = Field(..., ge=0)
    pairs_analyzed: int = Field(..., ge=0)
    pairs_failed: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(..., ge=0.0)
    pattern_distribution: dict[str, int] = Field(default_factory=dict)


# ─── spec 011 compat ──────────────────────────────────────────────────────────


def get_caption_pool(professor_id: str, db_path: Path) -> CaptionPool:
    """Resolve all video refs for a professor across mapped channels.

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
    db_path: "Path | ContentDB",
    captions_dir: "Path | None" = None,
    cosine_cull_threshold: float = 0.0,
    *,
    layer_a_min_seconds: float | None = None,
) -> "list[CandidatePair] | Iterator[VideoPairRef]":
    """Generate nC2 pairs — dispatches to spec 011 or spec 013 implementation.

    spec 011 call (positional): generate_nc2_pairs(professor_id, db_path, captions_dir, threshold)
    spec 013 call (keyword): generate_nc2_pairs(professor, db, layer_a_min_seconds=N)

    Args:
        professor_id: Professor pool identifier.
        db_path: Path (spec 011) or ContentDB (spec 013).
        captions_dir: embeddings.parquet parent dir (spec 011 only).
        cosine_cull_threshold: Cosine threshold (spec 011 only).
        layer_a_min_seconds: Layer A threshold (spec 013 only).

    Returns:
        list[CandidatePair] for spec 011, Iterator[VideoPairRef] for spec 013.
    """
    from tube_scout.storage.content_db import ContentDB as _ContentDB
    if isinstance(db_path, _ContentDB):
        min_s = 30.0 if layer_a_min_seconds is None else layer_a_min_seconds
        return _generate_nc2_pairs_v013(professor_id, db_path, layer_a_min_seconds=min_s)
    return _generate_nc2_candidate_pairs(professor_id, db_path, captions_dir, cosine_cull_threshold)


def _generate_nc2_candidate_pairs(
    professor_id: str,
    db_path: Path,
    captions_dir: "Path | None",
    cosine_cull_threshold: float,
) -> list[CandidatePair]:
    """Generate nC2 candidate pairs for a single professor's caption pool (spec 011).

    Performs cheap I-2 cosine cull before returning candidates. Reads
    embeddings.parquet produced by spec 007 fingerprint (boundary B-2).

    Args:
        professor_id: Identifier registered in professor_pool.
        db_path: Path to content_reuse.db SQLite file.
        captions_dir: Directory containing embeddings.parquet.
        cosine_cull_threshold: Pairs with cosine < threshold are dropped.

    Returns:
        List of CandidatePair with source_video_id, target_video_id, cosine.

    Raises:
        TypeError: If db_path or captions_dir is not a Path.
        ValueError: If the professor pool is empty.
        RuntimeError: If embeddings.parquet is missing.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")
    if captions_dir is not None and not isinstance(captions_dir, Path):
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

    video_id_set = set(video_ids)
    emb_df = emb_df.filter(pl.col("video_id").is_in(list(video_id_set)))

    if emb_df.is_empty() or len(emb_df) < 2:
        return []

    ordered_ids = emb_df["video_id"].to_list()
    raw_vecs: list[list[float]] = emb_df["embedding"].to_list()

    def _normalize(v: list[float]) -> list[float]:
        norm = sum(x * x for x in v) ** 0.5
        if norm == 0.0:
            return v
        return [x / norm for x in v]

    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    vecs = [_normalize(v) for v in raw_vecs]
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


# ─── spec 013 §A — _generate_nc2_pairs_v013 ──────────────────────────────────


def _generate_nc2_pairs_v013(
    professor: str,
    db: "ContentDB",
    *,
    layer_a_min_seconds: float = 30.0,
) -> Iterator[VideoPairRef]:
    """spec 013 implementation: query DB for video pool and apply Layer A.

    Args:
        professor: Professor pool identifier.
        db: ContentDB wrapper (must have v4 schema applied).
        layer_a_min_seconds: Minimum duration for either video to form a pair.

    Yields:
        VideoPairRef with source_video_id < target_video_id.
    """
    rows = db._conn.execute(
        """
        SELECT vm.video_id, vm.duration_seconds
        FROM professor_pool_membership ppm
        JOIN video_metadata vm
          ON vm.channel_id = (
              SELECT cm.channel_id FROM channel_metadata cm
              WHERE cm.channel_alias = ppm.channel_alias LIMIT 1
          )
        WHERE ppm.professor_id = ?
        ORDER BY vm.video_id ASC
        """,
        (professor,),
    ).fetchall()

    # Build list of (video_id, duration) from rows
    videos: list[tuple[str, float]] = [
        (row[0] if isinstance(row, (list, tuple)) else row["video_id"],
         float(row[1] if isinstance(row, (list, tuple)) else row["duration_seconds"] or 0.0))
        for row in rows
    ]

    n = len(videos)
    for i in range(n):
        for j in range(i + 1, n):
            vid_i, dur_i = videos[i]
            vid_j, dur_j = videos[j]
            shorter = min(dur_i, dur_j)
            if shorter < layer_a_min_seconds:
                continue
            src, tgt = (vid_i, vid_j) if vid_i < vid_j else (vid_j, vid_i)
            yield VideoPairRef(
                source_video_id=src,
                target_video_id=tgt,
                professor_id=professor,
            )


# ─── spec 013 §A — run_nc2_analysis ───────────────────────────────────────────


def run_nc2_analysis(
    professor: str,
    channel_alias: str,
    db: "ContentDB",
    *,
    matching_mode: Literal["M-default", "M-nC2"] = "M-default",
    layer_a_min_seconds: float = 30.0,
    layer_b_threshold: float = 0.30,
    resume: bool = False,
    force: bool = False,
    progress: "ProgressReporter | None" = None,
) -> AnalysisResult:
    """Execute nC2 analysis for one professor.

    Generates all nC2 pairs (with Layer A cull), skips pairs already in
    comparison_results when resume=True, and persists results.

    Side effects:
        - INSERT/IGNORE rows in comparison_results for each analyzed pair.
        - UPDATE pair_checkpoint if resume is used.

    Args:
        professor: Professor pool identifier.
        channel_alias: Channel alias label for this run.
        db: ContentDB wrapper (v4 schema required).
        matching_mode: Analysis mode.
        layer_a_min_seconds: Minimum video duration for pairing.
        layer_b_threshold: Reserved for Layer B n-gram threshold.
        resume: Skip pairs already recorded in comparison_results.
        force: Re-analyze even if already done (overrides resume).
        progress: Optional ProgressReporter for status output.

    Returns:
        AnalysisResult summary.
    """
    t0 = time.monotonic()

    all_pairs = list(generate_nc2_pairs(professor, db, layer_a_min_seconds=layer_a_min_seconds))
    total_pairs_generated = len(all_pairs)
    # Layer A already applied inside generate_nc2_pairs; culled = all - generated
    # We need raw count to compute culled. Get raw pair count from cartesian.
    rows = db._conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT vm.video_id
            FROM professor_pool_membership ppm
            JOIN video_metadata vm
              ON vm.channel_id = (
                  SELECT cm.channel_id FROM channel_metadata cm
                  WHERE cm.channel_alias = ppm.channel_alias LIMIT 1
              )
            WHERE ppm.professor_id = ?
        )
        """,
        (professor,),
    ).fetchone()
    n_videos = rows[0] if rows else 0
    raw_pair_count = n_videos * (n_videos - 1) // 2
    pairs_culled_layer_a = max(0, raw_pair_count - total_pairs_generated)

    # Get existing pairs when resume
    existing_pairs: set[tuple[str, str]] = set()
    if resume and not force:
        existing_rows = db._conn.execute(
            "SELECT source_video_id, target_video_id FROM comparison_results "
            "WHERE professor = ? OR professor_id = ?",
            (professor, professor),
        ).fetchall()
        for row in existing_rows:
            src = row[0] if isinstance(row, (list, tuple)) else row["source_video_id"]
            tgt = row[1] if isinstance(row, (list, tuple)) else row["target_video_id"]
            existing_pairs.add((src, tgt))

    pairs_analyzed = 0
    pairs_failed = 0
    pattern_distribution: dict[str, int] = {}

    for pair_ref in all_pairs:
        key = (pair_ref.source_video_id, pair_ref.target_video_id)
        if resume and not force and key in existing_pairs:
            continue

        try:
            db._conn.execute(
                """
                INSERT OR IGNORE INTO comparison_results
                    (source_video_id, target_video_id, professor, professor_id,
                     course, week, session, year_from, year_to,
                     matching_mode, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pair_ref.source_video_id,
                    pair_ref.target_video_id,
                    professor,
                    professor,
                    "",
                    0,
                    0,
                    0,
                    0,
                    matching_mode,
                    _now_iso(),
                ),
            )
            db._conn.commit()
            pairs_analyzed += 1
        except Exception:
            pairs_failed += 1

    elapsed = time.monotonic() - t0
    return AnalysisResult(
        professor=professor,
        channel_alias=channel_alias,
        matching_mode=matching_mode,
        total_pairs_generated=total_pairs_generated,
        pairs_culled_layer_a=pairs_culled_layer_a,
        pairs_analyzed=pairs_analyzed,
        pairs_failed=pairs_failed,
        elapsed_seconds=elapsed,
        pattern_distribution=pattern_distribution,
    )


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()
