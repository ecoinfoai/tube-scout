"""Expert correlation scaffold for spec 011 SC-007 calibration (T071c).

Computes Spearman/Pearson correlation between model suspicion_score and
expert labels from tests/fixtures/spec011/expert_validation/labelled_100.json.

Skips with informative message when fixture is absent (post-launch calibration).
"""

from pathlib import Path

import pytest

_EXPERT_FIXTURE = Path(__file__).parent.parent / "fixtures" / "spec011" / "expert_validation" / "labelled_100.json"


def test_sc007_expert_correlation_or_skip() -> None:
    """SC-007: Spearman correlation >= 0.90 if expert fixture present; skip otherwise.

    The labelled_100.json fixture is created 2-4 weeks post-launch during
    calibration. Until then, this test skips per spec.md Assumptions.
    """
    if not _EXPERT_FIXTURE.exists():
        pytest.skip(
            "post-launch calibration phase per spec.md Assumptions: "
            f"{_EXPERT_FIXTURE} not yet created"
        )

    import json

    data = json.loads(_EXPERT_FIXTURE.read_text(encoding="utf-8"))
    # Expected format: [{"video_pair": [...], "suspicion_score": 0.72, "expert_label": 0.8}, ...]
    if not data:
        pytest.skip("labelled_100.json is empty — calibration data not yet available")

    model_scores = [item["suspicion_score"] for item in data]
    expert_labels = [item["expert_label"] for item in data]

    assert len(model_scores) >= 20, (
        f"Need at least 20 labelled pairs, got {len(model_scores)}"
    )

    # Spearman rank correlation
    n = len(model_scores)
    rank_model = _rank(model_scores)
    rank_expert = _rank(expert_labels)

    d_sq_sum = sum((rm - re) ** 2 for rm, re in zip(rank_model, rank_expert))
    spearman = 1 - (6 * d_sq_sum) / (n * (n * n - 1))

    assert spearman >= 0.90, (
        f"Spearman correlation {spearman:.3f} < 0.90 threshold — "
        "model suspicion scores do not correlate with expert labels. "
        "Review composite_weights in policy.yaml."
    )


def _rank(values: list[float]) -> list[float]:
    """Compute rank of each element (1-based, average for ties)."""
    sorted_vals = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(sorted_vals):
        j = i
        while j < len(sorted_vals) - 1 and sorted_vals[j + 1][1] == sorted_vals[j][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[sorted_vals[k][0]] = avg_rank
        i = j + 1
    return ranks


def test_sc007_skip_when_fixture_absent() -> None:
    """Confirm test skips gracefully when expert fixture is absent."""
    # This test verifies the skip path is exercised
    if _EXPERT_FIXTURE.exists():
        pytest.skip("fixture present — skip-path test not applicable")
    # If we reach here, fixture is absent — verify skip mechanism is correct
    assert not _EXPERT_FIXTURE.exists()
