"""RED tests for ReusePatternLabel v4 extension (spec 013 T013).

Ref: data-model.md §E-10.
"""

from tube_scout.models.reuse_v2 import ReusePatternLabel

_BASELINE_VALUES = {
    "whole-same-week",
    "scattered-same-week",
    "whole-different-week",
    "scattered-different-week",
}


def test_re_recorded_same_content_label_exists() -> None:
    """RE_RECORDED_SAME_CONTENT must exist with value 're-recorded-same-content'."""
    assert ReusePatternLabel.RE_RECORDED_SAME_CONTENT == "re-recorded-same-content"


def test_tail_update_label_exists() -> None:
    """TAIL_UPDATE must exist with value 'tail-update'."""
    assert ReusePatternLabel.TAIL_UPDATE == "tail-update"


def test_existing_4_patterns_still_present() -> None:
    """Baseline 4 labels must remain unchanged after v4 extension."""
    enum_values = {label.value for label in ReusePatternLabel}
    assert _BASELINE_VALUES <= enum_values
