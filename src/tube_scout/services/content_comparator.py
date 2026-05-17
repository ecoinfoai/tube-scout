"""Content comparator for multi-indicator reuse detection.

Computes 5 independent indicators for each comparison pair and derives
a composite suspicion score with priority grade assignment.

spec 011 addendum (FR-008): compute_suspicion_score accepts optional
i6/i7/i8 and a PolicyConfig for 8-indicator weighted scoring. When
i6/i7/i8 are None (M-default mode), weights are renormalized over i1~i5
only so M-default scores remain comparable within their own grade bands.
"""

import logging
import math
from typing import Any

from tube_scout.models.content import SuspicionGrade, SuspicionScore

logger = logging.getLogger(__name__)

# Indicator weights (R-005 from research.md) — used by spec 007 path
WEIGHT_I1_HASH = 30.0
WEIGHT_I2_COSINE = 25.0
WEIGHT_I3_CHANGE = 20.0
WEIGHT_I4_TERMS = 15.0
WEIGHT_I5_DURATION = 10.0

# Grade thresholds (R-005 / spec 011 FR-008 — same boundaries)
GRADE_CRITICAL = 80.0
GRADE_HIGH = 60.0
GRADE_MODERATE = 40.0


def compute_change_rate(source_text: str, target_text: str) -> float:
    """Compute text change rate between source and target.

    Uses word-level set difference to measure how much the text changed.
    Returns 0.0 for identical texts, 1.0 for completely different texts.

    Args:
        source_text: Text from the source (older) video.
        target_text: Text from the target (newer) video.

    Returns:
        Change rate as float between 0.0 and 1.0.
    """
    if not source_text and not target_text:
        return 0.0
    if not source_text:
        return 1.0

    source_words = set(source_text.split())
    target_words = set(target_text.split())

    if not source_words and not target_words:
        return 0.0
    if not source_words:
        return 1.0

    all_words = source_words | target_words
    changed = source_words.symmetric_difference(target_words)
    return len(changed) / len(all_words) if all_words else 0.0


def compute_new_term_count(source_text: str, target_text: str) -> int:
    """Count terms in target that do not appear in source.

    Args:
        source_text: Text from the source (older) video.
        target_text: Text from the target (newer) video.

    Returns:
        Number of new terms.
    """
    source_words = set(source_text.split())
    target_words = set(target_text.split())
    return len(target_words - source_words)


def compute_duration_diff(source_duration: float, target_duration: float) -> float:
    """Compute absolute duration difference in seconds.

    Args:
        source_duration: Duration of source video in seconds.
        target_duration: Duration of target video in seconds.

    Returns:
        Absolute difference in seconds.
    """
    return abs(target_duration - source_duration)


def compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        vec_a: First embedding vector.
        vec_b: Second embedding vector.

    Returns:
        Cosine similarity between 0.0 and 1.0.
    """
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def grade_from_score(score: float) -> SuspicionGrade:
    """Assign priority grade based on suspicion score.

    Args:
        score: Suspicion score (0-100).

    Returns:
        SuspicionGrade enum value.
    """
    if score >= GRADE_CRITICAL:
        return SuspicionGrade.CRITICAL
    if score >= GRADE_HIGH:
        return SuspicionGrade.HIGH
    if score >= GRADE_MODERATE:
        return SuspicionGrade.MODERATE
    return SuspicionGrade.NORMAL


def _grade_from_score_8(score: float) -> str:
    """Return grade string for an 8-indicator composite score.

    Args:
        score: Float in 0.0~100.0.

    Returns:
        One of 'critical', 'high', 'moderate', 'normal'.
    """
    if score >= GRADE_CRITICAL:
        return "critical"
    if score >= GRADE_HIGH:
        return "high"
    if score >= GRADE_MODERATE:
        return "moderate"
    return "normal"


def compute_suspicion_score(
    *,
    i1_hash_match: bool,
    i2_cosine_similarity: float,
    i3_change_rate: float,
    i4_new_term_count: int,
    i5_duration_diff_seconds: float,
    i6_longest_contiguous_seconds: float | None = None,
    i7_distribution_dispersion: float | None = None,
    i8_position_diversity: float | None = None,
    policy: "Any | None" = None,
) -> "SuspicionScore | tuple[float, str]":
    """Compute composite suspicion score from 5 or 8 indicators.

    When i6/i7/i8 and policy are provided, uses 8-indicator weighted scoring
    (FR-008). When i6/i7/i8 are None (M-default mode), renormalizes weights
    over i1~i5 only to preserve grade-band semantics.

    Indicator normalization to 0~1 (higher = more suspicious):
    - i1 (hash_match): 1.0 if True else 0.0
    - i2 (cosine): already 0~1
    - i3 (change_rate): 1.0 - change_rate (lower change = more suspicious)
    - i4 (new_term_count): max(0, 1 - count/100) capped
    - i5 (duration_diff_seconds): max(0, 1 - diff/600) capped
    - i6 (longest_contiguous_seconds): min(1, seconds/1200) capped
    - i7 (distribution_dispersion): max(0, 1 - stdev/300) inverted
    - i8 (position_diversity): already 0~1

    Args:
        i1_hash_match: Whether SHA-256 hashes are identical.
        i2_cosine_similarity: Cosine similarity (0.0-1.0).
        i3_change_rate: Text change rate (0.0-1.0, 0=identical).
        i4_new_term_count: Number of new terms in target.
        i5_duration_diff_seconds: Absolute duration difference.
        i6_longest_contiguous_seconds: I-6 value; None → M-default mode.
        i7_distribution_dispersion: I-7 value; None → M-default mode.
        i8_position_diversity: I-8 value; None → M-default mode.
        policy: PolicyConfig with composite_weights; None → use spec 007 weights.

    Returns:
        If policy is provided (spec 011 path): tuple[float, str] = (score, grade).
        If policy is None (spec 007 path): SuspicionScore for backward compat.
    """
    # spec 011 path: policy provided → return (score, grade) tuple
    if policy is not None:
        weights = policy.composite_weights

        # Normalize all indicators
        n1 = 1.0 if i1_hash_match else 0.0
        n2 = float(i2_cosine_similarity)
        n3 = max(0.0, 1.0 - float(i3_change_rate))
        n4 = max(0.0, 1.0 - float(i4_new_term_count) / 100.0)
        n5 = max(0.0, 1.0 - abs(float(i5_duration_diff_seconds)) / 600.0)

        use_time_axis = (
            i6_longest_contiguous_seconds is not None
            and i7_distribution_dispersion is not None
            and i8_position_diversity is not None
        )

        if use_time_axis:
            n6 = min(1.0, float(i6_longest_contiguous_seconds) / 1200.0)
            n7 = max(0.0, 1.0 - float(i7_distribution_dispersion) / 300.0)
            n8 = float(i8_position_diversity)

            score = (
                n1 * weights.get("i1", 0.0) * 100.0
                + n2 * weights.get("i2", 0.0) * 100.0
                + n3 * weights.get("i3", 0.0) * 100.0
                + n4 * weights.get("i4", 0.0) * 100.0
                + n5 * weights.get("i5", 0.0) * 100.0
                + n6 * weights.get("i6", 0.0) * 100.0
                + n7 * weights.get("i7", 0.0) * 100.0
                + n8 * weights.get("i8", 0.0) * 100.0
            )
        else:
            # M-default renormalization: use only i1~i5 weights, renorm to sum=1
            w_slice = {k: weights.get(k, 0.0) for k in ("i1", "i2", "i3", "i4", "i5")}
            w_total = sum(w_slice.values())
            if w_total <= 0:
                w_total = 1.0
            score = (
                n1 * w_slice["i1"] / w_total * 100.0
                + n2 * w_slice["i2"] / w_total * 100.0
                + n3 * w_slice["i3"] / w_total * 100.0
                + n4 * w_slice["i4"] / w_total * 100.0
                + n5 * w_slice["i5"] / w_total * 100.0
            )

        score = max(0.0, min(100.0, score))
        return round(score, 2), _grade_from_score_8(score)

    # spec 007 backward-compat path: return SuspicionScore
    n1 = 1.0 if i1_hash_match else 0.0
    n2 = i2_cosine_similarity
    n3 = 1.0 - i3_change_rate
    n4 = 1.0 / (1.0 + i4_new_term_count)
    n5 = max(0.0, 1.0 - abs(i5_duration_diff_seconds) / 60.0)

    c1 = n1 * WEIGHT_I1_HASH
    c2 = n2 * WEIGHT_I2_COSINE
    c3 = n3 * WEIGHT_I3_CHANGE
    c4 = n4 * WEIGHT_I4_TERMS
    c5 = n5 * WEIGHT_I5_DURATION

    score = max(0.0, min(100.0, c1 + c2 + c3 + c4 + c5))

    return SuspicionScore(
        score=round(score, 2),
        grade=grade_from_score(score),
        i1_contribution=round(c1, 2),
        i2_contribution=round(c2, 2),
        i3_contribution=round(c3, 2),
        i4_contribution=round(c4, 2),
        i5_contribution=round(c5, 2),
    )


def match_comparison_pairs(
    parsed_titles: list[dict[str, Any]],
    *,
    year_from: int,
    year_to: int,
) -> list[dict[str, Any]]:
    """Match comparison pairs from parsed title data.

    Matches videos with same professor + course + week + session
    across year_from and year_to. Excludes parse errors and entries
    with missing required fields.

    Args:
        parsed_titles: List of parsed title dicts.
        year_from: Source year.
        year_to: Target year.

    Returns:
        List of pair dicts with source_video_id, target_video_id,
        professor, course, week, session.
    """
    # Build lookup: (professor, course, week, session) -> video_id per year
    source_map: dict[tuple, str] = {}
    target_map: dict[tuple, str] = {}

    for title in parsed_titles:
        if title.get("parse_error"):
            continue

        professor_list = title.get("professor", [])
        professor = professor_list[0] if professor_list else None
        course = title.get("course")
        week = title.get("week")
        session = title.get("session")
        year = title.get("year")

        # Skip if any required field is missing
        required = [
            professor,
            course,
            week is not None,
            session is not None,
            year is not None,
        ]
        if not all(required):
            continue

        key = (professor, course, week, session)

        if year == year_from:
            source_map[key] = title["video_id"]
        elif year == year_to:
            target_map[key] = title["video_id"]

    # Generate pairs from matching keys
    pairs: list[dict[str, Any]] = []
    for key, source_vid in source_map.items():
        if key in target_map:
            professor, course, week, session = key
            pairs.append({
                "source_video_id": source_vid,
                "target_video_id": target_map[key],
                "professor": professor,
                "course": course,
                "week": week,
                "session": session,
                "year_from": year_from,
                "year_to": year_to,
            })

    return pairs


class ContentComparator:
    """High-level comparator that orchestrates pair matching and indicator computation.

    Args:
        fingerprint_lookup: Callable to get fingerprint by video_id.
        embedding_lookup: Callable to get embedding vector by video_id.
        duration_lookup: Callable to get video duration by video_id.
        text_lookup: Callable to get full caption text by video_id.
    """

    def __init__(
        self,
        *,
        fingerprint_lookup: Any = None,
        embedding_lookup: Any = None,
        duration_lookup: Any = None,
        text_lookup: Any = None,
    ) -> None:
        """Initialize comparator with data lookup functions.

        Args:
            fingerprint_lookup: Returns fingerprint dict for a video_id.
            embedding_lookup: Returns embedding vector for a video_id.
            duration_lookup: Returns duration in seconds for a video_id.
            text_lookup: Returns full caption text for a video_id.
        """
        self._fingerprint_lookup = fingerprint_lookup
        self._embedding_lookup = embedding_lookup
        self._duration_lookup = duration_lookup
        self._text_lookup = text_lookup

    def compare_pair(self, pair: dict[str, Any]) -> dict[str, Any]:
        """Compare a single pair and compute all 5 indicators.

        Args:
            pair: Pair dict with source_video_id, target_video_id, etc.

        Returns:
            Enriched pair dict with i1-i5 indicators and suspicion score.
        """
        src_id = pair["source_video_id"]
        tgt_id = pair["target_video_id"]

        # I-1: Hash match
        src_fp = self._fingerprint_lookup(src_id) if self._fingerprint_lookup else None
        tgt_fp = self._fingerprint_lookup(tgt_id) if self._fingerprint_lookup else None
        i1_hash_match = (
            src_fp is not None
            and tgt_fp is not None
            and src_fp.get("sha256_hash") == tgt_fp.get("sha256_hash")
        )

        # I-2: Cosine similarity
        i2_cosine = 0.0
        if self._embedding_lookup:
            src_emb = self._embedding_lookup(src_id)
            tgt_emb = self._embedding_lookup(tgt_id)
            if src_emb is not None and tgt_emb is not None:
                i2_cosine = compute_cosine_similarity(src_emb, tgt_emb)

        # I-3: Change rate
        i3_change_rate = 1.0
        src_text = self._text_lookup(src_id) if self._text_lookup else None
        tgt_text = self._text_lookup(tgt_id) if self._text_lookup else None
        if src_text is not None and tgt_text is not None:
            i3_change_rate = compute_change_rate(src_text, tgt_text)

        # I-4: New term count
        i4_new_terms = 0
        if src_text is not None and tgt_text is not None:
            i4_new_terms = compute_new_term_count(src_text, tgt_text)

        # I-5: Duration difference
        i5_duration_diff = 60.0  # Default to 60s (neutral)
        if self._duration_lookup:
            src_dur = self._duration_lookup(src_id)
            tgt_dur = self._duration_lookup(tgt_id)
            if src_dur is not None and tgt_dur is not None:
                i5_duration_diff = compute_duration_diff(src_dur, tgt_dur)

        # Compute suspicion score
        suspicion = compute_suspicion_score(
            i1_hash_match=i1_hash_match,
            i2_cosine_similarity=i2_cosine,
            i3_change_rate=i3_change_rate,
            i4_new_term_count=i4_new_terms,
            i5_duration_diff_seconds=i5_duration_diff,
        )

        return {
            **pair,
            "i1_hash_match": i1_hash_match,
            "i2_cosine_similarity": round(i2_cosine, 4),
            "i3_change_rate": round(i3_change_rate, 4),
            "i4_new_term_count": i4_new_terms,
            "i5_duration_diff_seconds": round(i5_duration_diff, 2),
            "suspicion_score": suspicion.score,
            "grade": suspicion.grade.value,
        }
