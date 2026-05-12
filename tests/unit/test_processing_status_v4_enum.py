"""RED tests for spec 013 v4 enum extensions in tube_scout.models.content.

T010: VALID_PROCESSING_STATUSES must include spec 012 baseline values PLUS
      asr_in_progress and asr_failed.
      VALID_MATCH_CONFIDENCES must be a new frozenset with high/medium/ambiguous.
Ref: data-model.md §E-8.
"""

from tube_scout.models.content import VALID_MATCH_CONFIDENCES, VALID_PROCESSING_STATUSES

_SPEC012_BASELINE = frozenset({
    "pending",
    "collecting",
    "collected",
    "fingerprinted",
    "compared",
    "failed",
    "no_caption",
})

_V4_ADDITIONS = frozenset({"asr_in_progress", "asr_failed"})


def test_valid_processing_statuses_retains_spec012_baseline() -> None:
    """spec 012 baseline values must all remain in the set."""
    assert _SPEC012_BASELINE <= VALID_PROCESSING_STATUSES


def test_valid_processing_statuses_includes_v4_additions() -> None:
    """v4 adds asr_in_progress and asr_failed to the processing status set."""
    assert _V4_ADDITIONS <= VALID_PROCESSING_STATUSES


def test_valid_processing_statuses_is_frozenset() -> None:
    """VALID_PROCESSING_STATUSES must be a frozenset."""
    assert isinstance(VALID_PROCESSING_STATUSES, frozenset)


def test_valid_match_confidences_exists_and_is_frozenset() -> None:
    """VALID_MATCH_CONFIDENCES must exist and be a frozenset."""
    assert isinstance(VALID_MATCH_CONFIDENCES, frozenset)


def test_valid_match_confidences_exact_values() -> None:
    """VALID_MATCH_CONFIDENCES must contain exactly high, medium, ambiguous."""
    assert VALID_MATCH_CONFIDENCES == frozenset({"high", "medium", "ambiguous"})
