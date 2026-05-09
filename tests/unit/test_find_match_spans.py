"""Unit tests for find_match_spans greedy algorithm (T035 RED).

Tests the segment-alignment greedy anchor+extension algorithm that
powers I-6/I-7/I-8 computation in the time-axis indicators service.
"""

from typing import Any

import pytest


def _seg(start: float, end: float, text: str) -> dict[str, Any]:
    return {"start": start, "end": end, "text": text}


def _identity(text: str) -> str:
    return text


def test_anchor_extension_left_right() -> None:
    """Three consecutive matching segments form one MatchSpan via greedy extension."""
    from tube_scout.services.time_axis_indicators import find_match_spans

    segs_a = [
        _seg(0.0, 5.0, "alpha"),
        _seg(5.0, 10.0, "beta"),
        _seg(10.0, 15.0, "gamma"),
    ]
    segs_b = [
        _seg(0.0, 5.0, "alpha"),
        _seg(5.0, 10.0, "beta"),
        _seg(10.0, 15.0, "gamma"),
    ]
    spans = find_match_spans(segs_a, segs_b, normalize=_identity)

    assert len(spans) == 1
    assert spans[0].length_seconds == pytest.approx(15.0)
    assert spans[0].start_a_seconds == 0.0
    assert spans[0].end_a_seconds == 15.0


def test_normalized_exact_match() -> None:
    """Segments differing only in punctuation/case match after normalize_phrase."""
    from tube_scout.services.time_axis_indicators import find_match_spans
    from tube_scout.services.phrase_whitelist import normalize_phrase

    segs_a = [_seg(0.0, 5.0, "Hello, World!")]
    segs_b = [_seg(0.0, 5.0, "hello world")]
    spans = find_match_spans(segs_a, segs_b, normalize=normalize_phrase)

    assert len(spans) == 1


def test_minimum_span_emission() -> None:
    """A single matching segment still produces a span (even if length is small)."""
    from tube_scout.services.time_axis_indicators import find_match_spans

    segs_a = [_seg(0.0, 2.0, "same"), _seg(2.0, 4.0, "different_a")]
    segs_b = [_seg(0.0, 2.0, "same"), _seg(2.0, 4.0, "different_b")]
    spans = find_match_spans(segs_a, segs_b, normalize=_identity)

    assert len(spans) == 1
    assert spans[0].length_seconds == pytest.approx(2.0)


def test_sorted_by_start() -> None:
    """Result list is sorted by start_a_seconds ascending."""
    from tube_scout.services.time_axis_indicators import find_match_spans

    # Two disjoint matching blocks in reverse order in B
    segs_a = [
        _seg(0.0, 5.0, "block_one"),
        _seg(5.0, 10.0, "unique_a"),
        _seg(10.0, 15.0, "block_two"),
    ]
    segs_b = [
        _seg(0.0, 5.0, "block_two"),
        _seg(5.0, 10.0, "unique_b"),
        _seg(10.0, 15.0, "block_one"),
    ]
    spans = find_match_spans(segs_a, segs_b, normalize=_identity)

    assert len(spans) == 2
    assert spans[0].start_a_seconds <= spans[1].start_a_seconds


def test_consumed_segments_not_reanchored() -> None:
    """A segment consumed as part of a span cannot become a new anchor."""
    from tube_scout.services.time_axis_indicators import find_match_spans

    # A has [x, x, x]; B has [x, x, x] — greedy should produce 1 span not 3
    segs_a = [_seg(float(i * 5), float(i * 5 + 5), "shared") for i in range(3)]
    segs_b = [_seg(float(i * 5), float(i * 5 + 5), "shared") for i in range(3)]
    spans = find_match_spans(segs_a, segs_b, normalize=_identity)

    assert len(spans) == 1
    assert spans[0].length_seconds == pytest.approx(15.0)


def test_callable_normalize_injection() -> None:
    """Injecting an uppercase normalize changes match results."""
    from tube_scout.services.time_axis_indicators import find_match_spans

    segs_a = [_seg(0.0, 5.0, "hello")]
    segs_b = [_seg(0.0, 5.0, "HELLO")]

    # With identity normalize → no match
    spans_no_match = find_match_spans(segs_a, segs_b, normalize=_identity)
    # With casefold normalize → match
    spans_match = find_match_spans(segs_a, segs_b, normalize=str.casefold)

    assert len(spans_no_match) == 0
    assert len(spans_match) == 1
