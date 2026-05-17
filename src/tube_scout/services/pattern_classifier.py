"""Pattern classifier service for spec 011 reuse pattern labelling.

Classifies a comparison pair into one of four reuse patterns based on
I-6 contiguity ratio and week alignment flag.

spec 013 §D adds classify() with RE_RECORDED_SAME_CONTENT and TAIL_UPDATE.
"""

from typing import TYPE_CHECKING

from tube_scout.models.content import ComparisonResult
from tube_scout.models.reuse_v2 import MatchSpan, PolicyConfig, ReusePatternLabel

if TYPE_CHECKING:
    pass


def classify_reuse_pattern(
    comparison: ComparisonResult,
    durations: tuple[float, float],
    same_week: bool,
    policy: PolicyConfig,
) -> ReusePatternLabel:
    """Return one of 4 pattern labels using I-6 ratio + I-7 distribution + week flag.

    The whole-vs-scattered decision is based on:
        ratio = i6_longest_contiguous_seconds / min(durations)
        if ratio >= policy.pattern_whole_threshold_ratio → WHOLE, else SCATTERED

    Args:
        comparison: ComparisonResult with i6_longest_contiguous_seconds populated.
        durations: (duration_a, duration_b) in seconds for the two videos.
        same_week: True if both videos are from the same course week.
        policy: PolicyConfig containing pattern_whole_threshold_ratio.

    Returns:
        ReusePatternLabel indicating the pattern classification.

    Raises:
        ValueError: If i6_longest_contiguous_seconds is None.
        ValueError: If both durations are 0 (cannot compute ratio).
    """
    if comparison.i6_longest_contiguous_seconds is None:
        raise ValueError(
            "i6_longest_contiguous_seconds must not be None for pattern classification"
        )

    min_duration = min(durations)
    if min_duration <= 0.0:
        raise ValueError(
            f"duration must be positive to compute contiguity ratio, got {durations}"
        )

    ratio = comparison.i6_longest_contiguous_seconds / min_duration
    is_whole = ratio >= policy.pattern_whole_threshold_ratio

    if is_whole and same_week:
        return ReusePatternLabel.WHOLE_SAME_WEEK
    if is_whole and not same_week:
        return ReusePatternLabel.WHOLE_DIFF_WEEK
    if not is_whole and same_week:
        return ReusePatternLabel.SCATTERED_SAME_WEEK
    return ReusePatternLabel.SCATTERED_DIFF_WEEK


# ─── spec 013 §D: classify() with 6 patterns ─────────────────────────────────


_WHOLE_THRESHOLD_RATIO = 0.80  # i6/min_duration >= this → "whole"


def classify(
    pair: ComparisonResult,
    src_duration: float,
    tgt_duration: float,
    audio_fp_hamming: int | None,
    spans: list[MatchSpan],
    *,
    same_week: bool,
    audio_fp_hamming_threshold: int = 50,
) -> ReusePatternLabel:
    """Classify pair into one of 6 patterns per spec 013 §D decision tree.

    Decision tree (in priority order):
      1. RE_RECORDED_SAME_CONTENT override:
         audio_fp_hamming > threshold AND i2 >= 0.85 AND i6/min_dur >= 0.50
      2. TAIL_UPDATE override:
         i8_first_half >= 0.85 AND i8_second_half <= 0.15
      3. Base classification:
         i6/min_dur >= 0.80 → "whole", else "scattered"
         same_week → "same-week", else "different-week"

    Args:
        pair: ComparisonResult with i6_longest_contiguous_seconds populated.
        src_duration: Source video duration in seconds.
        tgt_duration: Target video duration in seconds.
        audio_fp_hamming: Chromaprint hamming distance, or None if unavailable.
        spans: Matching spans used for i8 half-split calculation.
        same_week: True if both videos are from the same course week.
        audio_fp_hamming_threshold: Hamming distance above which audio is "different".

    Returns:
        ReusePatternLabel for this pair.

    Raises:
        ValueError: If i6_longest_contiguous_seconds is None.
        ValueError: If both durations are 0.
    """
    if pair.i6_longest_contiguous_seconds is None:
        raise ValueError(
            "i6_longest_contiguous_seconds must not be None for pattern classification"
        )

    min_duration = min(src_duration, tgt_duration)
    if min_duration <= 0.0:
        raise ValueError(
            f"duration must be positive to compute contiguity ratio, "
            f"got ({src_duration}, {tgt_duration})"
        )

    i6 = pair.i6_longest_contiguous_seconds

    # Override 1: RE_RECORDED_SAME_CONTENT
    if (
        audio_fp_hamming is not None
        and audio_fp_hamming > audio_fp_hamming_threshold
        and pair.i2_cosine_similarity is not None
        and pair.i2_cosine_similarity >= 0.85
        and i6 / min_duration >= 0.50
    ):
        return ReusePatternLabel.RE_RECORDED_SAME_CONTENT

    # Override 2: TAIL_UPDATE via i8 half-split
    from tube_scout.services.time_axis_indicators import compute_i8_half_split

    i8_first, i8_second = compute_i8_half_split(spans, src_duration)
    if i8_first >= 0.85 and i8_second <= 0.15:
        return ReusePatternLabel.TAIL_UPDATE

    # Base classification
    is_whole = i6 / min_duration >= _WHOLE_THRESHOLD_RATIO
    if is_whole and same_week:
        return ReusePatternLabel.WHOLE_SAME_WEEK
    if is_whole and not same_week:
        return ReusePatternLabel.WHOLE_DIFF_WEEK
    if not is_whole and same_week:
        return ReusePatternLabel.SCATTERED_SAME_WEEK
    return ReusePatternLabel.SCATTERED_DIFF_WEEK
