"""Unit tests for pattern_classifier service (T043 RED).

Tests classify_reuse_pattern with all 4 label outcomes.
"""

from pathlib import Path

import pytest

from tube_scout.models.reuse_v2 import PolicyConfig, ReusePatternLabel
from tube_scout.models.content import ComparisonResult


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
