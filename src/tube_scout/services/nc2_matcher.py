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


# spec 013 §B / FR-026: normalize processing_status.caption_source into the
# audit-friendly source_type tokens that comparison_results.source_type_pair
# expects. Anything unknown falls back to "unknown" so the column is never NULL.
_SOURCE_TYPE_NORMALIZE: dict[str, str] = {
    "whisper": "asr",
    "faster-whisper": "asr",
    "asr": "asr",
    "transcript_api": "api",
    "captions_api": "api",
    "api": "api",
    "manual": "manual",
}


def _normalize_source_type(raw: str | None) -> str:
    """Normalize a raw caption_source value to {asr, api, manual, unknown}.

    Args:
        raw: Value read from ``processing_status.caption_source``.

    Returns:
        Normalized token. ``None`` and unrecognized values become ``"unknown"``.
    """
    if not raw:
        return "unknown"
    return _SOURCE_TYPE_NORMALIZE.get(raw.lower(), "unknown")


_SOURCE_TYPE_PRIORITY: dict[str, int] = {
    "manual": 0,
    "asr": 1,
    "api": 2,
    "unknown": 3,
}


def _source_type_pair(a: str, b: str) -> str:
    """Priority-ordered source-type pair label (FR-026).

    Tokens are ordered by ``manual < asr < api < unknown`` so the resulting
    label is canonical regardless of pair direction. Examples — ``"asr-asr"``,
    ``"asr-api"`` (not ``"api-asr"``), ``"manual-asr"``.

    Args:
        a: Normalized source type for source video.
        b: Normalized source type for target video.

    Returns:
        Hyphen-joined ordered label.
    """
    return "-".join(sorted([a, b], key=lambda t: _SOURCE_TYPE_PRIORITY.get(t, 99)))


def _audio_fp_metrics(
    source_video_id: str,
    target_video_id: str,
    db_path: Path,
) -> tuple[int | None, float | None, float | None]:
    """Compute hamming + offset + overlap between two audio_fingerprint rows.

    Reads both fingerprints from ``audio_fingerprint``; decodes with
    chromaprint; runs ``best_alignment_hamming`` to find the lowest-distance
    offset within ±400 frames. Frame duration is the chromaprint default
    8192 samples @ 11 025 Hz ≈ 0.124 s (FR-032).

    Args:
        source_video_id: First video id of the pair.
        target_video_id: Second video id of the pair.
        db_path: Path to content_reuse.db.

    Returns:
        Tuple ``(hamming_bits, best_offset_seconds, overlap_seconds)``. Any
        component is ``None`` if either fingerprint row is missing or decode
        fails — callers can persist NULLs without further branching.
    """
    from tube_scout.storage.content_db import get_audio_fingerprint

    src = get_audio_fingerprint(db_path, source_video_id)
    tgt = get_audio_fingerprint(db_path, target_video_id)
    if src is None or tgt is None:
        return None, None, None

    src_fp_b64 = src[0]
    tgt_fp_b64 = tgt[0]
    try:
        from tube_scout.services.audio_fingerprint import (
            best_alignment_hamming,
            decode_fingerprint_to_array,
        )

        src_arr = decode_fingerprint_to_array(src_fp_b64)
        tgt_arr = decode_fingerprint_to_array(tgt_fp_b64)
    except Exception:
        return None, None, None

    try:
        hamming_per_int, best_offset_frames = best_alignment_hamming(src_arr, tgt_arr)
    except Exception:
        return None, None, None

    frame_seconds = 8192.0 / 11025.0
    overlap_frames = min(len(src_arr), len(tgt_arr)) - abs(best_offset_frames)
    overlap_seconds = max(0.0, overlap_frames * frame_seconds)
    hamming_bits = int(round(hamming_per_int))
    best_offset_seconds = float(best_offset_frames) * frame_seconds
    return hamming_bits, best_offset_seconds, overlap_seconds


def _lookup_source_type(video_id: str, db_path: Path) -> str:
    """Read processing_status.caption_source for a video, return normalized token."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT caption_source FROM processing_status WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    finally:
        conn.close()
    return _normalize_source_type(row[0] if row else None)


def _resolve_transcript_path_by_video(
    video_id: str, data_dir: Path, db: ContentDB
) -> Path | None:
    """Resolve ``<data_dir>/<channel_alias>/02_analyze/transcripts/<video_id>.json``.

    Uses video_metadata + channel_metadata in the DB to find which channel a
    video belongs to (a professor pool may span multiple channels). Returns
    ``None`` if the channel mapping is missing or the JSON file is absent.

    Args:
        video_id: Video identifier.
        data_dir: Operator-provided collect data root (parent of channel
            work dirs). collect ingest writes ``<data_dir>/<alias>/02_analyze
            /transcripts/<video_id>.json`` per spec 018 atomic write.
        db: ContentDB wrapper to query the metadata tables.

    Returns:
        Path to the per-video transcript JSON, or ``None`` if not found.
    """
    row = db._conn.execute(
        "SELECT cm.channel_alias "
        "FROM video_metadata vm "
        "JOIN channel_metadata cm ON cm.channel_id = vm.channel_id "
        "WHERE vm.video_id = ?",
        (video_id,),
    ).fetchone()
    if row is None:
        return None
    alias = row[0] if isinstance(row, (list, tuple)) else row["channel_alias"]
    if not alias:
        return None
    path = data_dir / alias / "02_analyze" / "transcripts" / f"{video_id}.json"
    return path if path.is_file() else None


def _load_transcript_segments(
    transcript_root: Path | None,
    video_id: str,
    *,
    data_dir: Path | None = None,
    db: ContentDB | None = None,
) -> list[dict[str, float | str]]:
    """Load segments from a per-video transcript JSON (spec 018 schema).

    The path is resolved in two ways:

    * If ``transcript_root`` is provided, look at
      ``<transcript_root>/<video_id>.json`` (legacy single-channel layout
      and what the integration tests use).
    * Else if ``data_dir`` + ``db`` are provided, use
      :func:`_resolve_transcript_path_by_video` so multi-channel professor
      pools can find the right channel's transcript directory.

    Args:
        transcript_root: Optional flat directory containing per-video JSONs.
        video_id: Video identifier (JSON filename stem).
        data_dir: Optional collect data root for multi-channel resolution.
        db: ContentDB used to map video_id → channel_alias.

    Returns:
        List of ``{"start", "end", "text"}`` dicts; empty list when the
        transcript is missing, unreadable, or has no usable segments.
    """
    import json

    if transcript_root is not None:
        path: Path | None = transcript_root / f"{video_id}.json"
        if path is not None and not path.is_file():
            path = None
    elif data_dir is not None and db is not None:
        path = _resolve_transcript_path_by_video(video_id, data_dir, db)
    else:
        path = None

    if path is None:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_segs = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(raw_segs, list):
        return []
    out: list[dict[str, float | str]] = []
    for seg in raw_segs:
        if not isinstance(seg, dict):
            continue
        if "start" not in seg or "text" not in seg:
            continue
        # spec 018 segments use start/duration; tolerate both shapes
        start = float(seg["start"])
        if "end" in seg:
            end = float(seg["end"])
        elif "duration" in seg:
            end = start + float(seg["duration"])
        else:
            continue
        out.append({"start": start, "end": end, "text": str(seg["text"])})
    return out


def _persist_match_spans_for_pair(
    *,
    comparison_id: int,
    captions_a: list[dict[str, float | str]],
    captions_b: list[dict[str, float | str]],
    professor: str,
    db_path: Path,
    layer_a_min_seconds: float,
) -> None:
    """Compute, layer-filter, and persist match_spans for one comparison row.

    Flow (spec 013 T068):
      1. ``find_match_spans`` aligns the two segment lists.
      2. Layer A drops spans below ``layer_a_min_seconds``.
      3. Layer B marks (does not drop) spans whose normalized text matches
         the professor's baseline corpus; both retained and marked spans go
         into ``match_spans`` so reviewers can audit Layer B decisions.
      4. ``insert_match_spans`` UPSERTs into the table (idempotent).

    Args:
        comparison_id: Foreign key into ``comparison_results.id``.
        captions_a: Segments for the source video.
        captions_b: Segments for the target video.
        professor: Professor pool identifier (Layer B lookup).
        db_path: Path to ``content_reuse.db``.
        layer_a_min_seconds: Layer A minimum span length filter.
    """
    if not captions_a or not captions_b:
        return

    from tube_scout.services.baseline_corpus import list_baseline
    from tube_scout.services.phrase_whitelist import normalize_phrase
    from tube_scout.services.time_axis_indicators import find_match_spans
    from tube_scout.storage.content_db import insert_match_spans

    spans = find_match_spans(captions_a, captions_b)
    spans = [s for s in spans if s.length_seconds >= layer_a_min_seconds]
    if not spans:
        return

    baseline_phrases = list_baseline(professor, db_path)
    baseline_norms = {p.phrase_normalized for p in baseline_phrases}

    marked = [
        s.model_copy(
            update={
                "baseline_subtracted": normalize_phrase(s.matched_text_sample)
                in baseline_norms
            }
        )
        for s in spans
    ]
    insert_match_spans(comparison_id, marked, db_path)


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
    db_path: Path | ContentDB,
    captions_dir: Path | None = None,
    cosine_cull_threshold: float = 0.0,
    *,
    layer_a_min_seconds: float | None = None,
) -> list[CandidatePair] | Iterator[VideoPairRef]:
    """Generate nC2 pairs — dispatches to spec 011 or spec 013 implementation.

    spec 011 call (positional):
        generate_nc2_pairs(professor_id, db_path, captions_dir, threshold)
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
        return _generate_nc2_pairs_v013(
            professor_id, db_path, layer_a_min_seconds=min_s
        )
    return _generate_nc2_candidate_pairs(
        professor_id, db_path, captions_dir, cosine_cull_threshold
    )


def _generate_nc2_candidate_pairs(
    professor_id: str,
    db_path: Path,
    captions_dir: Path | None,
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
        raise TypeError(
            f"captions_dir must be a Path, got {type(captions_dir).__name__}"
        )

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
    db: ContentDB,
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
        (
            row[0] if isinstance(row, (list, tuple)) else row["video_id"],
            float(
                row[1]
                if isinstance(row, (list, tuple))
                else row["duration_seconds"] or 0.0
            ),
        )
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
    db: ContentDB,
    *,
    matching_mode: Literal["M-default", "M-nC2"] = "M-default",
    layer_a_min_seconds: float = 30.0,
    layer_b_threshold: float = 0.30,
    resume: bool = False,
    force: bool = False,
    progress: ProgressReporter | None = None,
    transcript_root: Path | None = None,
    data_dir: Path | None = None,
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
    from tube_scout.services import pair_checkpoint as _pc

    t0 = time.monotonic()

    all_pairs = list(
        generate_nc2_pairs(professor, db, layer_a_min_seconds=layer_a_min_seconds)
    )
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

    # FR-031 (spec 013 T069): record this run as a pair_checkpoint row.
    run_id = _pc.start_run(
        professor_id=professor,
        matching_mode=matching_mode,
        pair_count_total=total_pairs_generated,
        db_path=db.db_path,
    )

    pairs_analyzed = 0
    pairs_failed = 0
    pattern_distribution: dict[str, int] = {}

    for pair_ref in all_pairs:
        key = (pair_ref.source_video_id, pair_ref.target_video_id)
        if resume and not force and key in existing_pairs:
            continue

        try:
            # FR-026: classify source-pair type from caption_source on each side.
            src_type = _lookup_source_type(pair_ref.source_video_id, db.db_path)
            tgt_type = _lookup_source_type(pair_ref.target_video_id, db.db_path)
            source_type_pair = _source_type_pair(src_type, tgt_type)

            # FR-032: audio fingerprint distance + best offset + overlap seconds.
            audio_fp_hamming, audio_fp_best_offset, audio_fp_overlap = (
                _audio_fp_metrics(
                    pair_ref.source_video_id,
                    pair_ref.target_video_id,
                    db.db_path,
                )
            )

            db._conn.execute(
                """
                INSERT OR IGNORE INTO comparison_results
                    (source_video_id, target_video_id, professor, professor_id,
                     course, week, session, year_from, year_to,
                     matching_mode, source_type_pair,
                     audio_fp_hamming, audio_fp_best_offset, audio_fp_overlap_seconds,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    source_type_pair,
                    audio_fp_hamming,
                    audio_fp_best_offset,
                    audio_fp_overlap,
                    _now_iso(),
                ),
            )
            db._conn.commit()

            # spec 013 T068: persist match_spans + Layer B baseline marking.
            if transcript_root is not None or data_dir is not None:
                row = db._conn.execute(
                    "SELECT id FROM comparison_results "
                    "WHERE source_video_id = ? AND target_video_id = ? "
                    "AND matching_mode = ?",
                    (pair_ref.source_video_id, pair_ref.target_video_id, matching_mode),
                ).fetchone()
                if row is not None:
                    comparison_id = (
                        row[0] if isinstance(row, (list, tuple)) else row["id"]
                    )
                    captions_a = _load_transcript_segments(
                        transcript_root,
                        pair_ref.source_video_id,
                        data_dir=data_dir,
                        db=db,
                    )
                    captions_b = _load_transcript_segments(
                        transcript_root,
                        pair_ref.target_video_id,
                        data_dir=data_dir,
                        db=db,
                    )
                    _persist_match_spans_for_pair(
                        comparison_id=int(comparison_id),
                        captions_a=captions_a,
                        captions_b=captions_b,
                        professor=professor,
                        db_path=db.db_path,
                        layer_a_min_seconds=layer_a_min_seconds,
                    )

            _pc.mark_pair_done(run_id, db.db_path)
            pairs_analyzed += 1
        except Exception:
            pairs_failed += 1

    _pc.finalize_run(run_id, db.db_path, "completed")

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
