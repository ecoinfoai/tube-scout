"""Evidence-score based mp4 ↔ video_id mapping service.

FR-003, FR-004: compute per-signal evidence scores and decide confidence bucket.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tube_scout.models.content import VideoMetadata

# Invisible characters that survive a re.sub punctuation strip and would
# otherwise prevent two visually-identical titles from matching (e.g.
# zero-width joiner pasted in from a YouTube studio title). audit v3
# F-21 / ADV-51.
_ZERO_WIDTH_CHARS = "​‌‍﻿"
_ZERO_WIDTH_TABLE = {ord(c): None for c in _ZERO_WIDTH_CHARS}

ConfidenceBucket = Literal["high", "medium", "ambiguous"]

DEFAULT_HIGH_THRESHOLD: int = 65
DEFAULT_MEDIUM_THRESHOLD: int = 40

_NORMALIZE_PATTERN = re.compile(r"[\s\-_.,()\[\]?!~]+")


# ---------------------------------------------------------------------------
# EvidenceSignals
# ---------------------------------------------------------------------------


class EvidenceSignals(BaseModel):
    """Per-(mp4, video_id) candidate signal breakdown."""

    exact_title_match: bool
    normalized_title_match: bool
    duration_match_within_1s: bool
    size_ratio_plausible: bool
    mtime_match_within_1d: bool

    @property
    def score(self) -> int:
        """Compute evidence score from signals.

        Returns:
            Integer score. exact_title_match=40 (or normalized=30), duration=25,
            size=5, mtime=5. Max=75.
        """
        s = 0
        if self.exact_title_match:
            s += 40
        elif self.normalized_title_match:
            s += 30
        if self.duration_match_within_1s:
            s += 25
        if self.size_ratio_plausible:
            s += 5
        if self.mtime_match_within_1d:
            s += 5
        return s


# ---------------------------------------------------------------------------
# MappingDecision
# ---------------------------------------------------------------------------


class MappingDecision(BaseModel):
    """Result of decide_mapping for a single mp4 file."""

    mp4_path: Path
    video_id: str | None
    score: int
    confidence: ConfidenceBucket | None
    signals: EvidenceSignals | None
    candidates: list[tuple[str, int]]

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------


def _normalize_for_match(s: str) -> str:
    """Normalize string for fuzzy title matching.

    Applies Unicode NFC normalization (so NFD-decomposed Hangul / Latin
    pasted from external editors compares equal to NFC sources) and
    strips zero-width characters before the punctuation/whitespace regex
    pass. audit v3 F-21 / ADV-50 + ADV-51.

    Args:
        s: Raw string to normalize.

    Returns:
        Lowercased, NFC-normalized string with zero-width characters and
        punctuation/whitespace removed.
    """
    nfc = unicodedata.normalize("NFC", s)
    stripped = nfc.translate(_ZERO_WIDTH_TABLE)
    return _NORMALIZE_PATTERN.sub("", stripped).lower()


def _exact_title_match(mp4_filename: str, video_title: str) -> bool:
    return Path(mp4_filename).stem == video_title


def _normalized_title_match(mp4_filename: str, video_title: str) -> bool:
    """Match with normalization and 255-char truncation support.

    Args:
        mp4_filename: mp4 filename (basename).
        video_title: Video title from metadata.

    Returns:
        True if normalized stem equals normalized title, or if stem is a
        prefix of title (for OS 255-char truncation cases, stem >= 50 chars).
    """
    norm_stem = _normalize_for_match(Path(mp4_filename).stem)
    norm_title = _normalize_for_match(video_title)
    if norm_stem == norm_title:
        return True
    if len(norm_stem) >= 50 and norm_title.startswith(norm_stem):
        return True
    return False


def _probe_duration_via_ffprobe(mp4_path: Path) -> float | None:
    """Run ffprobe to get duration in seconds.

    On non-zero exit or parse failure, emits a module-level warning with
    the first 120 bytes of stderr so operators see why the duration
    signal was dropped (audit v3 F-21 / ADV-51).

    Args:
        mp4_path: Path to mp4 file.

    Returns:
        Duration in seconds, or None on failure.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            import logging

            logging.getLogger(__name__).warning(
                "ffprobe failed for %s: %s",
                mp4_path,
                (result.stderr or "")[:120].strip(),
            )
            return None
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        import logging

        logging.getLogger(__name__).warning("ffprobe error for %s: %s", mp4_path, exc)
        return None


def _duration_match(mp4_path: Path, video_duration_s: float, tol_s: float) -> bool:
    """Check if mp4 actual duration matches video metadata within tolerance.

    Args:
        mp4_path: Path to mp4 file.
        video_duration_s: Expected duration from video metadata (seconds).
        tol_s: Tolerance in seconds.

    Returns:
        True if |actual - expected| <= tol_s, False on ffprobe failure.
    """
    actual = _probe_duration_via_ffprobe(mp4_path)
    if actual is None:
        return False
    return abs(actual - video_duration_s) <= tol_s


def _size_ratio_plausible(mp4_path: Path, duration_s: float) -> bool:
    """Check if file size / duration ratio is in a plausible range.

    Args:
        mp4_path: Path to mp4 file.
        duration_s: Expected duration in seconds.

    Returns:
        True if bytes/second in [0.5 MB/s, 10 MB/s].
    """
    if duration_s <= 0:
        return False
    size_bytes = mp4_path.stat().st_size
    ratio = size_bytes / duration_s
    return 0.5e6 <= ratio <= 10e6


def _mtime_match(mp4_path: Path, created_at: datetime, tol_days: float) -> bool:
    """Check if mp4 mtime is within tolerance of video creation timestamp.

    Args:
        mp4_path: Path to mp4 file.
        created_at: Video creation timestamp (timezone-aware).
        tol_days: Tolerance in days.

    Returns:
        True if |mtime - created_at| <= tol_days * 86400 seconds.
    """
    mp4_mtime = datetime.fromtimestamp(mp4_path.stat().st_mtime, tz=UTC)
    delta = abs((mp4_mtime - created_at).total_seconds())
    return delta <= tol_days * 86400


def _duration_match_with_cached(
    mp4_duration_s: float | None,
    video_duration_s: float,
    tol_s: float,
) -> bool:
    """Check if a cached mp4 duration matches video metadata within tolerance.

    Args:
        mp4_duration_s: Cached ffprobe duration for the mp4, or None if
            ffprobe failed or was not yet run.
        video_duration_s: Expected duration from video metadata (seconds).
        tol_s: Tolerance in seconds.

    Returns:
        True if |mp4_duration_s - video_duration_s| <= tol_s.
        False when mp4_duration_s is None (ffprobe failure or cache miss).

    Examples:
        >>> _duration_match_with_cached(None, 100.0, 1.0)
        False
        >>> _duration_match_with_cached(99.5, 100.0, 1.0)
        True
        >>> _duration_match_with_cached(98.0, 100.0, 1.0)
        False
    """
    if mp4_duration_s is None:
        return False
    return abs(mp4_duration_s - video_duration_s) <= tol_s


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def score_mp4_candidates(
    mp4_path: Path,
    video_meta_list: list[VideoMetadata],
    *,
    duration_tolerance_seconds: float = 1.0,
    mtime_tolerance_days: float = 1.0,
    _ffprobe_cache: dict[str, float | None] | None = None,
    mtime_signal_disabled: bool = False,
) -> list[tuple[str, EvidenceSignals]]:
    """Compute evidence signals for every (mp4, video_id) candidate.

    Args:
        mp4_path: Takeout mp4 absolute path.
        video_meta_list: Channel video_metadata candidate list.
        duration_tolerance_seconds: Duration match tolerance (default 1.0s).
        mtime_tolerance_days: mtime match tolerance (default 1.0 day).
        _ffprobe_cache: Optional dict mapping resolved str(path) → duration
            seconds (or None on ffprobe failure). Key is always
            str(path.resolve()) so symlinks to the same physical file share
            one cache entry. If None, a fresh dict is created and ffprobe is
            called once for mp4_path. Pass a pre-populated dict to skip
            ffprobe entirely (useful for unit testing and batch callers that
            build the cache externally).
        mtime_signal_disabled: When True, force ``mtime_match_within_1d``
            to False regardless of file metadata. Used by batch callers
            that have detected an archive bulk-extraction signature
            (every mp4 in the channel sharing one mtime) to neutralize
            an otherwise useless signal. audit v3 F-21 / ADV-56.

    Returns:
        List of (video_id, EvidenceSignals) for every candidate.
    """
    if _ffprobe_cache is None:
        _ffprobe_cache = {}

    cache_key = str(mp4_path.resolve())
    if cache_key not in _ffprobe_cache:
        _ffprobe_cache[cache_key] = _probe_duration_via_ffprobe(mp4_path)
    cached_duration = _ffprobe_cache[cache_key]

    results: list[tuple[str, EvidenceSignals]] = []
    mp4_name = mp4_path.name

    for vm in video_meta_list:
        exact = _exact_title_match(mp4_name, vm.title)
        normalized = (not exact) and _normalized_title_match(mp4_name, vm.title)

        dur_s = vm.duration_seconds or 0.0
        dur_match = _duration_match_with_cached(
            cached_duration, dur_s, duration_tolerance_seconds
        )
        size_ok = _size_ratio_plausible(mp4_path, dur_s) if dur_s > 0 else False

        mtime_ok = False
        if not mtime_signal_disabled and vm.created_at is not None:
            created = vm.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            mtime_ok = _mtime_match(mp4_path, created, mtime_tolerance_days)

        signals = EvidenceSignals(
            exact_title_match=exact,
            normalized_title_match=normalized,
            duration_match_within_1s=dur_match,
            size_ratio_plausible=size_ok,
            mtime_match_within_1d=mtime_ok,
        )
        results.append((vm.video_id, signals))

    return results


def decide_mapping(
    mp4_path: Path,
    video_meta_list: list[VideoMetadata],
    *,
    high_threshold: int = DEFAULT_HIGH_THRESHOLD,
    medium_threshold: int = DEFAULT_MEDIUM_THRESHOLD,
) -> MappingDecision:
    """Decide the best mapping for one mp4 using the evidence score.

    Args:
        mp4_path: Single mp4 file path.
        video_meta_list: Channel video_metadata candidate list.
        high_threshold: High confidence bucket threshold (default 65).
        medium_threshold: Medium confidence bucket threshold (default 40).

    Returns:
        MappingDecision with chosen video_id (or None) + signal breakdown.
    """
    scored = score_mp4_candidates(mp4_path, video_meta_list)

    if not scored:
        return MappingDecision(
            mp4_path=mp4_path,
            video_id=None,
            score=0,
            confidence=None,
            signals=None,
            candidates=[],
        )

    scored_with_int = [(vid, sig, sig.score) for vid, sig in scored]
    scored_with_int.sort(key=lambda x: x[2], reverse=True)

    top_score = scored_with_int[0][2]
    top_candidates = [(vid, sc) for vid, _sig, sc in scored_with_int if sc == top_score]

    candidates_top3 = [(vid, sc) for vid, _sig, sc in scored_with_int[:3]]

    if top_score < medium_threshold:
        return MappingDecision(
            mp4_path=mp4_path,
            video_id=None,
            score=top_score,
            confidence=None,
            signals=scored_with_int[0][1],
            candidates=candidates_top3,
        )

    if len(top_candidates) > 1:
        return MappingDecision(
            mp4_path=mp4_path,
            video_id=None,
            score=top_score,
            confidence="ambiguous",
            signals=scored_with_int[0][1],
            candidates=candidates_top3,
        )

    best_vid, best_sig, best_score = scored_with_int[0]
    confidence: ConfidenceBucket = "high" if best_score >= high_threshold else "medium"

    return MappingDecision(
        mp4_path=mp4_path,
        video_id=best_vid,
        score=best_score,
        confidence=confidence,
        signals=best_sig,
        candidates=candidates_top3,
    )
