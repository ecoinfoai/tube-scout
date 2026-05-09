"""Pattern classifier service for spec 011 reuse pattern labelling.

Classifies a comparison pair into one of four reuse patterns based on
I-6 contiguity ratio and week alignment flag.
"""

from tube_scout.models.content import ComparisonResult
from tube_scout.models.reuse_v2 import PolicyConfig, ReusePatternLabel


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
