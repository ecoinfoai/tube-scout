"""Unit tests for pattern_classifier service (T043 RED).

Tests classify_reuse_pattern with all 4 label outcomes.
"""


import pytest

from tube_scout.models.content import ComparisonResult
from tube_scout.models.reuse_v2 import PolicyConfig, ReusePatternLabel


def _make_comparison(**kwargs) -> ComparisonResult:
    defaults = dict(
        source_video_id="vid_a",
        target_video_id="vid_b",
        professor="test-prof",
        course="CS101",
        week=1,
        session=1,
        year_from=2023,
        year_to=2024,
    )
    defaults.update(kwargs)
    return ComparisonResult(**defaults)


def test_whole_same_week_classification() -> None:
    """WHOLE_SAME_WEEK when i6/min_duration >= threshold and same_week=True."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig(pattern_whole_threshold_ratio=0.50)
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=1500.0,  # 1500/2400 = 0.625 >= 0.50
        i7_distribution_dispersion=0.0,
        i8_position_diversity=0.5,
    )
    result = classify_reuse_pattern(comparison, (2400.0, 2400.0), same_week=True, policy=policy)
    assert result == ReusePatternLabel.WHOLE_SAME_WEEK


def test_scattered_same_week_classification() -> None:
    """SCATTERED_SAME_WEEK when i6/min_duration < threshold and same_week=True."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig(pattern_whole_threshold_ratio=0.50)
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=300.0,  # 300/2400 = 0.125 < 0.50
        i7_distribution_dispersion=200.0,
        i8_position_diversity=0.8,
    )
    result = classify_reuse_pattern(comparison, (2400.0, 2400.0), same_week=True, policy=policy)
    assert result == ReusePatternLabel.SCATTERED_SAME_WEEK


def test_whole_diff_week_classification() -> None:
    """WHOLE_DIFF_WEEK when i6/min_duration >= threshold and same_week=False."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig(pattern_whole_threshold_ratio=0.50)
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=1800.0,  # 1800/2400 = 0.75 >= 0.50
        i7_distribution_dispersion=0.0,
        i8_position_diversity=0.3,
    )
    result = classify_reuse_pattern(comparison, (2400.0, 2400.0), same_week=False, policy=policy)
    assert result == ReusePatternLabel.WHOLE_DIFF_WEEK


def test_scattered_diff_week_classification() -> None:
    """SCATTERED_DIFF_WEEK when i6/min_duration < threshold and same_week=False."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig(pattern_whole_threshold_ratio=0.50)
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=200.0,  # 200/2400 = 0.083 < 0.50
        i7_distribution_dispersion=150.0,
        i8_position_diversity=0.9,
    )
    result = classify_reuse_pattern(comparison, (2400.0, 2400.0), same_week=False, policy=policy)
    assert result == ReusePatternLabel.SCATTERED_DIFF_WEEK


def test_uses_min_of_two_durations() -> None:
    """classify uses min(durations) so the shorter video is the reference."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig(pattern_whole_threshold_ratio=0.50)
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=600.0,  # 600/1000 = 0.60 >= 0.50 (min=1000)
        i7_distribution_dispersion=0.0,
        i8_position_diversity=0.3,
    )
    # min(1000, 2400) = 1000; 600/1000 = 0.60 >= 0.50 → WHOLE
    result = classify_reuse_pattern(comparison, (2400.0, 1000.0), same_week=True, policy=policy)
    assert result == ReusePatternLabel.WHOLE_SAME_WEEK


def test_fail_fast_on_none_i6() -> None:
    """classify_reuse_pattern raises ValueError if i6 is None."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig()
    comparison = _make_comparison(i6_longest_contiguous_seconds=None)
    with pytest.raises(ValueError, match="i6"):
        classify_reuse_pattern(comparison, (2400.0, 2400.0), same_week=True, policy=policy)


def test_fail_fast_on_zero_duration() -> None:
    """classify_reuse_pattern raises ValueError if both durations are 0."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    policy = PolicyConfig()
    comparison = _make_comparison(i6_longest_contiguous_seconds=100.0)
    with pytest.raises(ValueError, match="duration"):
        classify_reuse_pattern(comparison, (0.0, 0.0), same_week=True, policy=policy)


# ─── T061 RED — spec 013 §D: classify() with 2 new patterns ──────────────────


def _make_spans_for_classify(
    first_half_coverage: float = 0.0,
    second_half_coverage: float = 0.0,
    src_duration: float = 1000.0,
) -> list:
    """Create MatchSpan list approximating given half-split coverage."""
    from tube_scout.models.reuse_v2 import MatchSpan

    spans = []
    if first_half_coverage > 0.0:
        half = src_duration / 2.0
        end = half * first_half_coverage
        spans.append(MatchSpan(
            start_a_seconds=0.0,
            end_a_seconds=max(1.0, end),
            start_b_seconds=0.0,
            end_b_seconds=max(1.0, end),
            length_seconds=max(1.0, end),
            matched_text_sample="first half content",
        ))
    if second_half_coverage > 0.0:
        half = src_duration / 2.0
        start = half + 10.0
        end = half + half * second_half_coverage
        spans.append(MatchSpan(
            start_a_seconds=start,
            end_a_seconds=max(start + 1.0, end),
            start_b_seconds=start,
            end_b_seconds=max(start + 1.0, end),
            length_seconds=max(1.0, end - start),
            matched_text_sample="second half content",
        ))
    return spans


def test_classify_whole_same_week() -> None:
    """classify() returns WHOLE_SAME_WEEK for high I-6 ratio + same_week=True."""
    from tube_scout.services.pattern_classifier import classify
    from tube_scout.models.reuse_v2 import ReusePatternLabel

    comparison = _make_comparison(
        i6_longest_contiguous_seconds=1800.0,  # 1800/2400 = 0.75 >= 0.80 → whole
        i2_cosine_similarity=0.50,
    )
    spans = _make_spans_for_classify(first_half_coverage=0.9, second_half_coverage=0.9, src_duration=2400.0)
    result = classify(
        pair=comparison,
        src_duration=2400.0,
        tgt_duration=2400.0,
        audio_fp_hamming=None,
        spans=spans,
        same_week=True,
    )
    assert result == ReusePatternLabel.WHOLE_SAME_WEEK, f"Expected WHOLE_SAME_WEEK, got {result}"


def test_classify_scattered_different_week() -> None:
    """classify() returns SCATTERED_DIFF_WEEK for low I-6 ratio + same_week=False."""
    from tube_scout.services.pattern_classifier import classify
    from tube_scout.models.reuse_v2 import ReusePatternLabel

    comparison = _make_comparison(
        i6_longest_contiguous_seconds=200.0,  # 200/2400 = 0.083 < 0.80 → scattered
        i2_cosine_similarity=0.50,
    )
    spans = _make_spans_for_classify(first_half_coverage=0.2, second_half_coverage=0.2, src_duration=2400.0)
    result = classify(
        pair=comparison,
        src_duration=2400.0,
        tgt_duration=2400.0,
        audio_fp_hamming=None,
        spans=spans,
        same_week=False,
    )
    assert result == ReusePatternLabel.SCATTERED_DIFF_WEEK, f"Expected SCATTERED_DIFF_WEEK, got {result}"


def test_classify_re_recorded_same_content_when_audio_differs() -> None:
    """classify() returns RE_RECORDED_SAME_CONTENT when audio fp hamming > threshold
    and i2 cosine >= 0.85 and i6 covers >= 50% of shorter duration.
    """
    from tube_scout.services.pattern_classifier import classify
    from tube_scout.models.reuse_v2 import ReusePatternLabel

    # i6 = 1300 / 2000 = 0.65 >= 0.50 → qualifies for override
    # i2 >= 0.85 → qualifies
    # audio_fp_hamming = 80 > threshold(50) → re-recorded override
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=1300.0,
        i2_cosine_similarity=0.90,
    )
    spans = _make_spans_for_classify(first_half_coverage=0.8, second_half_coverage=0.3, src_duration=2000.0)
    result = classify(
        pair=comparison,
        src_duration=2000.0,
        tgt_duration=2000.0,
        audio_fp_hamming=80,   # > threshold 50 → re-recorded
        spans=spans,
        same_week=True,
        audio_fp_hamming_threshold=50,
    )
    assert result == ReusePatternLabel.RE_RECORDED_SAME_CONTENT, (
        f"Expected RE_RECORDED_SAME_CONTENT, got {result}"
    )


def test_classify_tail_update_when_i8_drops() -> None:
    """classify() returns TAIL_UPDATE when i8_first >= 0.85 and i8_second <= 0.15."""
    from tube_scout.services.pattern_classifier import classify
    from tube_scout.models.reuse_v2 import ReusePatternLabel

    # Spans concentrated in first half only → tail-update pattern
    comparison = _make_comparison(
        i6_longest_contiguous_seconds=300.0,  # 300/1000 = 0.30 < 0.80 → scattered
        i2_cosine_similarity=0.60,
    )
    # Only first-half spans; no second-half → i8_first high, i8_second = 0
    spans = _make_spans_for_classify(first_half_coverage=0.9, second_half_coverage=0.0, src_duration=1000.0)
    result = classify(
        pair=comparison,
        src_duration=1000.0,
        tgt_duration=1000.0,
        audio_fp_hamming=None,
        spans=spans,
        same_week=True,
    )
    assert result == ReusePatternLabel.TAIL_UPDATE, (
        f"Expected TAIL_UPDATE when content concentrated in first half only, got {result}"
    )
