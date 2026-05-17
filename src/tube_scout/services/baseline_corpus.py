"""Baseline corpus service for spec 011 Layer B phrase matching.

Provides bootstrap seeding from earliest videos, manual CRUD, and
span subtraction used by apply_layers Layer B.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tube_scout.models.reuse_v2 import (
    BaselineBootstrapReport,
    BaselinePhrase,
    MatchSpan,
)
from tube_scout.services.phrase_whitelist import normalize_phrase


def _now() -> str:
    return datetime.now(UTC).isoformat()


def bootstrap_baseline(
    professor_id: str,
    db_path: Path,
    captions_dir: Path,
    earliest_n: int = 5,
    min_occurrences: int = 3,
    registered_by: str = "system",
) -> BaselineBootstrapReport:
    """Seed baseline corpus from a professor's earliest videos.

    Idempotent: re-runs add to occurrences, do not duplicate phrases.

    Args:
        professor_id: Identifier registered in professor_pool.
        db_path: SQLite content_reuse.db path.
        captions_dir: Directory of caption JSON files (spec 010 output).
        earliest_n: How many caption files to scan for recurring phrases.
        min_occurrences: Minimum number of videos a phrase must appear in.
        registered_by: Admin or system identifier for audit trail.

    Returns:
        BaselineBootstrapReport summarizing how many phrases were added/skipped.

    Raises:
        TypeError: If db_path is not a Path.
        ValueError: If professor_id is empty.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")
    if not professor_id:
        raise ValueError("professor_id must not be empty")

    caption_files = sorted(captions_dir.glob("*.json"))[:earliest_n]

    phrase_to_video_ids: dict[str, list[str]] = {}
    for cap_file in caption_files:
        try:
            data = json.loads(cap_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        video_id = data.get("video_id", cap_file.stem)
        segments = data.get("segments", [])
        seen_in_this_video: set[str] = set()
        for seg in segments:
            raw = seg.get("text", "")
            norm = normalize_phrase(raw)
            if not norm:
                continue
            if norm not in seen_in_this_video:
                seen_in_this_video.add(norm)
                phrase_to_video_ids.setdefault(norm, []).append(video_id)

    phrases_added = 0
    phrases_skipped = 0
    sample_phrases: list[str] = []

    conn = sqlite3.connect(str(db_path))
    try:
        for norm, video_ids in phrase_to_video_ids.items():
            occurrence_count = len(video_ids)
            if occurrence_count < min_occurrences:
                phrases_skipped += 1
                continue
            raw = norm  # use normalized form as raw for bootstrap
            source_ids_json = json.dumps(list(dict.fromkeys(video_ids)))

            existing = conn.execute(
                "SELECT occurrences FROM baseline_corpus "
                "WHERE professor_id = ? AND phrase_normalized = ?",
                (professor_id, norm),
            ).fetchone()

            if existing is not None:
                conn.execute(
                    "UPDATE baseline_corpus SET occurrences = MAX(occurrences, ?) "
                    "WHERE professor_id = ? AND phrase_normalized = ?",
                    (occurrence_count, professor_id, norm),
                )
            else:
                conn.execute(
                    "INSERT INTO baseline_corpus "
                    "(professor_id, phrase_normalized, phrase_raw, occurrences, "
                    " source_video_ids, seeded, registered_at, registered_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        professor_id,
                        norm,
                        raw,
                        occurrence_count,
                        source_ids_json,
                        1,
                        _now(),
                        registered_by,
                    ),
                )
                phrases_added += 1
                if len(sample_phrases) < 5:
                    sample_phrases.append(raw)

        conn.commit()
    finally:
        conn.close()

    return BaselineBootstrapReport(
        professor_id=professor_id,
        phrases_added=phrases_added,
        phrases_skipped=phrases_skipped,
        sample_phrases=sample_phrases,
    )


def add_baseline_phrase(
    professor_id: str,
    phrase_raw: str,
    db_path: Path,
    source_video_ids: list[str] | None,
    registered_by: str,
) -> BaselinePhrase:
    """Manually register a recurring phrase. Normalization applied automatically.

    Args:
        professor_id: Professor pool identifier.
        phrase_raw: Raw phrase text as supplied by the admin.
        db_path: SQLite content_reuse.db path.
        source_video_ids: Optional list of video IDs that contain this phrase.
        registered_by: Admin identifier for audit trail.

    Returns:
        BaselinePhrase model of the newly inserted (or existing) phrase.

    Raises:
        TypeError: If db_path is not a Path.
        ValueError: If professor_id or phrase_raw is empty.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")
    if not professor_id:
        raise ValueError("professor_id must not be empty")
    if not phrase_raw or not phrase_raw.strip():
        raise ValueError("phrase_raw must not be empty")

    norm = normalize_phrase(phrase_raw)
    if not norm:
        raise ValueError(f"phrase_raw normalizes to empty string: {phrase_raw!r}")

    ids = source_video_ids or []
    source_ids_json = json.dumps(ids)

    conn = sqlite3.connect(str(db_path))
    try:
        existing = conn.execute(
            "SELECT id, occurrences, source_video_ids, seeded FROM baseline_corpus "
            "WHERE professor_id = ? AND phrase_normalized = ?",
            (professor_id, norm),
        ).fetchone()

        if existing is not None:
            conn.execute(
                "UPDATE baseline_corpus SET occurrences = occurrences + 1 "
                "WHERE professor_id = ? AND phrase_normalized = ?",
                (professor_id, norm),
            )
            occurrences = existing[1] + 1
            seeded = bool(existing[3])
        else:
            conn.execute(
                "INSERT INTO baseline_corpus "
                "(professor_id, phrase_normalized, phrase_raw, occurrences, "
                " source_video_ids, seeded, registered_at, registered_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    professor_id,
                    norm,
                    phrase_raw,
                    1,
                    source_ids_json,
                    0,
                    _now(),
                    registered_by,
                ),
            )
            occurrences = 1
            seeded = False
        conn.commit()
    finally:
        conn.close()

    return BaselinePhrase(
        professor_id=professor_id,
        phrase_normalized=norm,
        phrase_raw=phrase_raw,
        occurrences=occurrences,
        source_video_ids=ids,
        seeded=seeded,
    )


def list_baseline(professor_id: str | None, db_path: Path) -> list[BaselinePhrase]:
    """List baseline phrases, filtered by professor if given.

    Args:
        professor_id: Professor pool identifier, or None to list all.
        db_path: SQLite content_reuse.db path.

    Returns:
        List of BaselinePhrase models matching the filter.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    conn = sqlite3.connect(str(db_path))
    try:
        if professor_id is not None:
            rows = conn.execute(
                "SELECT professor_id, phrase_normalized, phrase_raw, occurrences, "
                "source_video_ids, seeded FROM baseline_corpus "
                "WHERE professor_id = ? ORDER BY occurrences DESC",
                (professor_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT professor_id, phrase_normalized, phrase_raw, occurrences, "
                "source_video_ids, seeded FROM baseline_corpus "
                "ORDER BY professor_id, occurrences DESC"
            ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        try:
            ids = json.loads(row[4]) if row[4] else []
        except (json.JSONDecodeError, TypeError):
            ids = []
        result.append(
            BaselinePhrase(
                professor_id=row[0],
                phrase_normalized=row[1],
                phrase_raw=row[2],
                occurrences=row[3],
                source_video_ids=ids,
                seeded=bool(row[5]),
            )
        )
    return result


def remove_baseline_phrase(
    professor_id: str,
    phrase_raw: str,
    db_path: Path,
) -> bool:
    """Remove. Returns True if removed, False if not found.

    Args:
        professor_id: Professor pool identifier.
        phrase_raw: Raw phrase text (normalized before lookup).
        db_path: SQLite content_reuse.db path.

    Returns:
        True if the phrase was found and removed, False otherwise.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    norm = normalize_phrase(phrase_raw)
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "DELETE FROM baseline_corpus "
            "WHERE professor_id = ? AND phrase_normalized = ?",
            (professor_id, norm),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def subtract_baseline(
    professor_id: str,
    spans: list[MatchSpan],
    db_path: Path,
) -> tuple[list[MatchSpan], float]:
    """Subtract baseline-matching spans, return (remaining spans, subtracted seconds).

    Spans whose matched_text_sample normalizes to a known baseline phrase are
    marked baseline_subtracted=True and excluded from the returned list.

    Args:
        professor_id: Professor pool identifier used to look up baseline phrases.
        spans: All match spans from time_axis analysis.
        db_path: SQLite content_reuse.db path.

    Returns:
        Tuple of (remaining non-baseline spans, total subtracted seconds).

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    baseline_phrases = list_baseline(professor_id, db_path)
    baseline_norms: set[str] = {p.phrase_normalized for p in baseline_phrases}

    remaining: list[MatchSpan] = []
    subtracted_seconds = 0.0

    for span in spans:
        norm = normalize_phrase(span.matched_text_sample)
        if norm in baseline_norms:
            subtracted_seconds += span.length_seconds
        else:
            remaining.append(span)

    return remaining, subtracted_seconds
