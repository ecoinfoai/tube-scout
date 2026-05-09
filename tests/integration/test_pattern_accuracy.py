"""Pattern accuracy tests against labelled_pairs fixture (T044a RED).

Requires >=95% accuracy over all 21 labelled pairs.
"""

import json
from pathlib import Path

import pytest

from tube_scout.models.reuse_v2 import PolicyConfig, ReusePatternLabel
from tube_scout.models.content import ComparisonResult


_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "spec011" / "patterns" / "labelled_pairs.json"

_PATTERN_MAP = {
    "whole-same-week": ReusePatternLabel.WHOLE_SAME_WEEK,
    "scattered-same-week": ReusePatternLabel.SCATTERED_SAME_WEEK,
    "whole-different-week": ReusePatternLabel.WHOLE_DIFF_WEEK,
    "scattered-different-week": ReusePatternLabel.SCATTERED_DIFF_WEEK,
}


def _comparison_from_pair(pair: dict) -> ComparisonResult:
    return ComparisonResult(
        source_video_id=pair["video_a"],
        target_video_id=pair["video_b"],
        professor="test-prof",
        course="CS101",
        week=1 if pair["same_week"] else 1,
        session=1,
        year_from=2023,
        year_to=2024 if not pair["same_week"] else 2023,
        i6_longest_contiguous_seconds=pair["expected_i6_min"],
    )


def test_pattern_accuracy_geq_95() -> None:
    """classify_reuse_pattern achieves >= 95% accuracy on all 21 labelled pairs."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    pairs = json.loads(_FIXTURE_PATH.read_text())
    policy = PolicyConfig(pattern_whole_threshold_ratio=0.50)

    correct = 0
    total = len(pairs)
    misses = []

    for pair in pairs:
        comparison = _comparison_from_pair(pair)
        expected = _PATTERN_MAP[pair["ground_truth_pattern"]]
        same_week = pair["same_week"]
        # Use representative duration of 2400s for the shorter video
        durations = (2400.0, 2400.0)
        got = classify_reuse_pattern(comparison, durations, same_week, policy)
        if got == expected:
            correct += 1
        else:
            misses.append(f"{pair['video_a']} vs {pair['video_b']}: expected {expected}, got {got}")

    accuracy = correct / total
    assert accuracy >= 0.95, (
        f"Pattern accuracy {accuracy:.1%} < 95% threshold. Misclassified:\n"
        + "\n".join(misses)
    )
