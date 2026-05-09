"""Pair checkpoint service for spec 011 nC2 resume support.

Manages pair_checkpoint table rows that track nC2 analysis run progress.
Implements iterate_unfinished_pairs to skip already-processed pairs,
enabling idempotent restart after interruption (FR-031, R-5).
"""

import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from tube_scout.models.reuse_v2 import CaptionPool, PairCheckpoint, VideoPairRef


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_run(
    professor_id: str,
    matching_mode: Literal["M-default", "M-nC2"],
    pair_count_total: int,
    db_path: Path,
) -> str:
    """Insert pair_checkpoint row, return run_id.

    Args:
        professor_id: Professor whose pool is being analysed.
        matching_mode: Analysis mode for this run.
        pair_count_total: Total number of pairs to process.
        db_path: Path to the SQLite database file.

    Returns:
        Unique run_id string for this run.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    run_id = f"nc2-{professor_id}-{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO pair_checkpoint "
            "(run_id, professor_id, matching_mode, pair_count_total, pair_count_done, "
            "started_at, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, professor_id, matching_mode, pair_count_total, 0, now, "in_progress"),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def iterate_unfinished_pairs(
    pool: CaptionPool,
    matching_mode: Literal["M-default", "M-nC2"],
    db_path: Path,
) -> Iterator[VideoPairRef]:
    """Yield only pairs not already present in comparison_results.

    Idempotent restart: re-running after interruption resumes from the
    next unfinished pair (FR-031, R-5). Pairs are checked against
    comparison_results for (source_video_id, target_video_id, matching_mode).

    Args:
        pool: CaptionPool containing all video refs for the professor.
        matching_mode: Analysis mode used for this run.
        db_path: Path to the SQLite database file.

    Yields:
        VideoPairRef for each pair not yet in comparison_results.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    from itertools import combinations

    conn = sqlite3.connect(str(db_path))
    try:
        existing = set(
            conn.execute(
                "SELECT source_video_id, target_video_id FROM comparison_results "
                "WHERE matching_mode = ?",
                (matching_mode,),
            ).fetchall()
        )
        # Also add reverse order to handle symmetric pairs
        existing_sym = existing | {(t, s) for s, t in existing}
    finally:
        conn.close()

    video_ids = [vr.video_id for vr in pool.video_refs]
    professor_id = pool.professor_id

    for vid_a, vid_b in combinations(video_ids, 2):
        if (vid_a, vid_b) not in existing_sym:
            yield VideoPairRef(
                source_video_id=vid_a,
                target_video_id=vid_b,
                professor_id=professor_id,
            )


def mark_pair_done(run_id: str, db_path: Path) -> None:
    """Increment pair_count_done and update last_pair_at.

    Args:
        run_id: Run identifier returned by start_run.
        db_path: Path to the SQLite database file.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    now = _now()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE pair_checkpoint SET pair_count_done = pair_count_done + 1, "
            "last_pair_at = ? WHERE run_id = ?",
            (now, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def finalize_run(
    run_id: str,
    db_path: Path,
    status: Literal["completed", "aborted"],
) -> PairCheckpoint:
    """Mark run complete (or aborted) and return final state.

    Args:
        run_id: Run identifier returned by start_run.
        db_path: Path to the SQLite database file.
        status: Final lifecycle status for this run.

    Returns:
        PairCheckpoint with the final run state.

    Raises:
        TypeError: If db_path is not a Path.
        ValueError: If run_id does not exist in pair_checkpoint.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "UPDATE pair_checkpoint SET status = ? WHERE run_id = ?",
            (status, run_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM pair_checkpoint WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No pair_checkpoint row found for run_id='{run_id}'.")
        return PairCheckpoint(
            run_id=row["run_id"],
            professor_id=row["professor_id"],
            matching_mode=row["matching_mode"],
            pair_count_total=row["pair_count_total"],
            pair_count_done=row["pair_count_done"],
            started_at=datetime.fromisoformat(row["started_at"]),
            last_pair_at=(
                datetime.fromisoformat(row["last_pair_at"])
                if row["last_pair_at"]
                else None
            ),
            status=row["status"],
        )
    finally:
        conn.close()


def resume_run(
    professor_id: str,
    matching_mode: Literal["M-default", "M-nC2"],
    db_path: Path,
) -> str | None:
    """Find existing in_progress run for professor+mode. Returns run_id or None.

    Args:
        professor_id: Professor identifier to search for.
        matching_mode: Analysis mode to search for.
        db_path: Path to the SQLite database file.

    Returns:
        run_id string if an in_progress run exists, None otherwise.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT run_id FROM pair_checkpoint "
            "WHERE professor_id = ? AND matching_mode = ? AND status = 'in_progress' "
            "ORDER BY started_at DESC LIMIT 1",
            (professor_id, matching_mode),
        ).fetchone()
    finally:
        conn.close()

    return row[0] if row else None
