"""Unit tests for 8-indicator composite score (T036a RED — FR-008 remediation).

Tests compute_suspicion_score from content_comparator with i6/i7/i8 support,
grade bucket boundaries, indicator normalization logic, and M-default
renormalization when i6/i7/i8 are None.
"""

import pytest

from tube_scout.models.reuse_v2 import PolicyConfig


def _default_policy() -> PolicyConfig:
    return PolicyConfig()


def _score(
    *,
    i1: bool = False,
    i2: float = 0.0,
    i3: float = 1.0,
    i4: int = 100,
    i5: float = 600.0,
    i6: float | None = 0.0,
    i7: float | None = 0.0,
    i8: float | None = 0.0,
    policy: PolicyConfig | None = None,
) -> tuple[float, str]:
    from tube_scout.services.content_comparator import compute_suspicion_score
    p = policy or _default_policy()
    return compute_suspicion_score(
        i1_hash_match=i1,
        i2_cosine_similarity=i2,
        i3_change_rate=i3,
        i4_new_term_count=i4,
        i5_duration_diff_seconds=i5,
        i6_longest_contiguous_seconds=i6,
        i7_distribution_dispersion=i7,
        i8_position_diversity=i8,
        policy=p,
    )


def test_all_max_yields_100() -> None:
    """All indicators at maximum suspicious values → score = 100, grade = 'critical'."""
    score, grade = _score(
        i1=True, i2=1.0, i3=0.0, i4=0, i5=0.0,
        i6=1200.0, i7=0.0, i8=1.0,
    )
    assert score == pytest.approx(100.0, abs=0.1)
    assert grade == "critical"


def test_all_zero_yields_0() -> None:
    """All indicators at minimum suspicious values → score = 0, grade = 'normal'."""
    score, grade = _score(
        i1=False, i2=0.0, i3=1.0, i4=100, i5=600.0,
        i6=0.0, i7=300.0, i8=0.0,
    )
    assert score == pytest.approx(0.0, abs=0.1)
    assert grade == "normal"


def test_whole_week_reaches_critical() -> None:
    """High hash+cosine+long contiguous block → grade = 'critical'."""
    score, grade = _score(
        i1=True, i2=0.95, i3=0.05, i4=0, i5=10.0,
        i6=1200.0, i7=0.0, i8=0.2,
    )
    assert grade == "critical", f"Expected critical, got {grade} (score={score:.2f})"


def test_scattered_diff_week_at_least_moderate() -> None:
    """Scattered reuse pattern: cosine=0.6, i6=300 → grade at least 'moderate'."""
    score, grade = _score(
        i1=False, i2=0.6, i3=0.4, i4=10, i5=60.0,
        i6=300.0, i7=200.0, i8=0.8,
    )
    assert grade in ("moderate", "high", "critical"), (
        f"Expected at least moderate, got {grade} (score={score:.2f})"
    )


def test_m_default_renormalizes_weights() -> None:
    """When i6/i7/i8 are None, only i1~i5 weights are used and renormalized to 1.0."""
    score_with, grade_with = _score(
        i1=True, i2=1.0, i3=0.0, i4=0, i5=0.0,
        i6=1200.0, i7=0.0, i8=1.0,
    )
    score_without, grade_without = _score(
        i1=True, i2=1.0, i3=0.0, i4=0, i5=0.0,
        i6=None, i7=None, i8=None,
    )
    # Both should reach critical when i1~i5 are all max
    assert grade_without == "critical", (
        f"Expected critical with None i6/i7/i8, got {grade_without} (score={score_without:.2f})"
    )
    # score_without should still be 100 (renormalized weights sum to 1)
    assert score_without == pytest.approx(100.0, abs=0.1), (
        f"Expected 100 with renormalized weights, got {score_without:.2f}"
    )


def test_grade_bucket_boundaries() -> None:
    """Verify grade boundaries: ≥80 critical, 60-79 high, 40-59 moderate, <40 normal."""
    from tube_scout.services.content_comparator import compute_suspicion_score

    policy = _default_policy()

    def score_to_grade(target: float) -> str:
        # Use i2 (cosine) as the primary driver since weight is 0.20
        # and set others to produce approximately the target score
        # Use None for i6/i7/i8 and drive via i1+i2+i3+i4+i5
        # With i1~i5 renormalized: i1=0.20, i2=0.20, i3=0.10, i4=0.05, i5=0.05 → sum=0.60
        # renorm factor = 1/0.60; i1=0.333, i2=0.333, ...
        # Just use direct score injection via a mock result
        _, grade = compute_suspicion_score(
            i1_hash_match=False,
            i2_cosine_similarity=target / 100.0,
            i3_change_rate=1.0 - (target / 100.0),
            i4_new_term_count=0,
            i5_duration_diff_seconds=0.0,
            i6_longest_contiguous_seconds=None,
            i7_distribution_dispersion=None,
            i8_position_diversity=None,
            policy=policy,
        )
        return grade

    # Verify grade function exists and returns strings
    from tube_scout.services.content_comparator import _grade_from_score_8
    assert _grade_from_score_8(80.0) == "critical"
    assert _grade_from_score_8(79.9) == "high"
    assert _grade_from_score_8(60.0) == "high"
    assert _grade_from_score_8(59.9) == "moderate"
    assert _grade_from_score_8(40.0) == "moderate"
    assert _grade_from_score_8(39.9) == "normal"


def test_inverted_change_rate() -> None:
    """I-3 inversion: change_rate=0 → max contribution, change_rate=1 → 0 contribution."""
    score_low_change, _ = _score(
        i1=False, i2=0.0, i3=0.0, i4=100, i5=600.0,
        i6=0.0, i7=300.0, i8=0.0,
    )
    score_high_change, _ = _score(
        i1=False, i2=0.0, i3=1.0, i4=100, i5=600.0,
        i6=0.0, i7=300.0, i8=0.0,
    )
    assert score_low_change > score_high_change, (
        f"I-3=0 should produce higher score than I-3=1: "
        f"{score_low_change:.2f} vs {score_high_change:.2f}"
    )
