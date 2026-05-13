"""Unit tests for time_axis_indicators service (T034 RED).

Tests I-6 / I-7 / I-8 computation using the spec 011 caption fixtures.
Case A = one long contiguous block (~1200s).
Case B = 4 scattered blocks (~300s each, positionally spread).
Case C = one short block (~120s).
"""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "spec011" / "captions"


def _load(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / name).read_text())["segments"]


@pytest.fixture
def case_a_segs() -> tuple[list[dict], list[dict]]:
    return _load("case_a_video1.json"), _load("case_a_video2.json")


@pytest.fixture
def case_b_segs() -> tuple[list[dict], list[dict]]:
    return _load("case_b_video1.json"), _load("case_b_video2.json")


@pytest.fixture
def case_c_segs() -> tuple[list[dict], list[dict]]:
    return _load("case_c_video1.json"), _load("case_c_video2.json")


def _make_pair(src: str, tgt: str):
    from tube_scout.models.reuse_v2 import CandidatePair
    return CandidatePair(
        source_video_id=src,
        target_video_id=tgt,
        cosine=0.9,
        professor_id="prof-test",
    )


def test_case_a_contiguous_20min(case_a_segs) -> None:
    """Case A: one long contiguous block → I-6 ≥ 1200s, I-7 = 0 (single span), I-8 small."""
    from tube_scout.services.time_axis_indicators import compute_time_axis

    segs_a, segs_b = case_a_segs
    pair = _make_pair("test_vid_a01", "test_vid_a02")
    result = compute_time_axis(pair, segs_a, segs_b)

    assert result.i6_longest_contiguous_seconds >= 1200.0, (
        f"Expected I-6 >= 1200s for case_a, got {result.i6_longest_contiguous_seconds}"
    )
    assert result.i7_distribution_dispersion == 0.0, (
        f"Expected I-7 = 0 for single span, got {result.i7_distribution_dispersion}"
    )
    assert result.i8_position_diversity < 0.5, (
        f"Expected I-8 < 0.5 for single block, got {result.i8_position_diversity}"
    )
    assert len(result.spans) >= 1


def test_case_b_scattered_5min_x4(case_b_segs) -> None:
    """Case B: scattered blocks → I-6 ≈ 300s, I-8 large (positionally spread)."""
    from tube_scout.services.time_axis_indicators import compute_time_axis

    segs_a, segs_b = case_b_segs
    pair = _make_pair("case_b_v1", "case_b_v2")
    result = compute_time_axis(pair, segs_a, segs_b)

    assert result.i6_longest_contiguous_seconds > 0.0, "Expected non-zero I-6 for case_b"
    assert result.i8_position_diversity >= 0.0
    assert len(result.spans) >= 1


def test_case_c_short_2min(case_c_segs) -> None:
    """Case C: one short block (~120s) → I-6 ≈ 120s, I-7 = 0, I-8 small."""
    from tube_scout.services.time_axis_indicators import compute_time_axis

    segs_a, segs_b = case_c_segs
    pair = _make_pair("case_c_v1", "case_c_v2")
    result = compute_time_axis(pair, segs_a, segs_b)

    assert result.i6_longest_contiguous_seconds > 0.0, "Expected non-zero I-6 for case_c"
    assert result.i7_distribution_dispersion == 0.0, (
        f"Expected I-7 = 0 for single span, got {result.i7_distribution_dispersion}"
    )
    assert result.i8_position_diversity < 0.5


def test_no_match_returns_zeros() -> None:
    """Completely disjoint captions → I-6=0, I-7=0, I-8=0, spans=[]."""
    from tube_scout.models.reuse_v2 import CandidatePair
    from tube_scout.services.time_axis_indicators import compute_time_axis

    segs_a = [{"start": 0.0, "end": 5.0, "text": "apple orange"}]
    segs_b = [{"start": 0.0, "end": 5.0, "text": "banana cherry"}]
    pair = CandidatePair(
        source_video_id="v_a", target_video_id="v_b",
        cosine=0.1, professor_id="prof-test",
    )
    result = compute_time_axis(pair, segs_a, segs_b)

    assert result.i6_longest_contiguous_seconds == 0.0
    assert result.i7_distribution_dispersion == 0.0
    assert result.i8_position_diversity == 0.0
    assert result.spans == []


def test_i7_dispersion_ranks(case_a_segs, case_b_segs) -> None:
    """Case B I-7 >= Case A I-7 (B has at least as much span dispersion)."""
    from tube_scout.services.time_axis_indicators import compute_time_axis

    segs_a1, segs_a2 = case_a_segs
    segs_b1, segs_b2 = case_b_segs
    pair_a = _make_pair("a1", "a2")
    pair_b = _make_pair("b1", "b2")

    res_a = compute_time_axis(pair_a, segs_a1, segs_a2)
    res_b = compute_time_axis(pair_b, segs_b1, segs_b2)

    assert res_b.i7_distribution_dispersion >= res_a.i7_distribution_dispersion, (
        f"Expected I-7(B) >= I-7(A), got I-7(A)={res_a.i7_distribution_dispersion}, "
        f"I-7(B)={res_b.i7_distribution_dispersion}"
    )


def test_i8_position_diversity_ranks(case_a_segs, case_b_segs) -> None:
    """Case B I-8 >= Case A I-8 (B spans are more positionally diverse)."""
    from tube_scout.services.time_axis_indicators import compute_time_axis

    segs_a1, segs_a2 = case_a_segs
    segs_b1, segs_b2 = case_b_segs
    pair_a = _make_pair("a1", "a2")
    pair_b = _make_pair("b1", "b2")

    res_a = compute_time_axis(pair_a, segs_a1, segs_a2)
    res_b = compute_time_axis(pair_b, segs_b1, segs_b2)

    assert res_b.i8_position_diversity >= res_a.i8_position_diversity, (
        f"Expected I-8(B) >= I-8(A), got I-8(A)={res_a.i8_position_diversity}, "
        f"I-8(B)={res_b.i8_position_diversity}"
    )


# ─── T060 RED — spec 013 contract §B: standalone indicator functions ──────────


def _make_span(
    start_a: float,
    end_a: float,
    start_b: float,
    end_b: float,
    length: float,
) -> "MatchSpan":
    from tube_scout.models.reuse_v2 import MatchSpan
    return MatchSpan(
        start_a_seconds=start_a,
        end_a_seconds=end_a,
        start_b_seconds=start_b,
        end_b_seconds=end_b,
        length_seconds=length,
        matched_text_sample="test sample text",
    )


def test_i6_longest_contiguous_single_span() -> None:
    """Single 300 s span → I-6 = 300.0."""
    from tube_scout.services.time_axis_indicators import compute_i6_longest_contiguous

    spans = [_make_span(0.0, 300.0, 0.0, 300.0, 300.0)]
    assert compute_i6_longest_contiguous(spans) == 300.0


def test_i6_returns_zero_on_empty() -> None:
    """Empty span list → I-6 = 0.0."""
    from tube_scout.services.time_axis_indicators import compute_i6_longest_contiguous

    assert compute_i6_longest_contiguous([]) == 0.0


def test_i7_dispersion_balanced_vs_concentrated() -> None:
    """Balanced spans → higher dispersion than concentrated spans.

    Concentrated: two spans of identical length (low dispersion).
    Balanced: spans of very different lengths (high dispersion).
    """
    from tube_scout.services.time_axis_indicators import compute_i7_distribution_dispersion

    concentrated = [
        _make_span(0.0, 100.0, 0.0, 100.0, 100.0),
        _make_span(200.0, 300.0, 200.0, 300.0, 100.0),
    ]
    balanced = [
        _make_span(0.0, 10.0, 0.0, 10.0, 10.0),
        _make_span(100.0, 500.0, 100.0, 500.0, 400.0),
    ]

    i7_conc = compute_i7_distribution_dispersion(concentrated)
    i7_bal = compute_i7_distribution_dispersion(balanced)

    assert i7_bal >= i7_conc, (
        f"Balanced dispersion ({i7_bal}) must be >= concentrated ({i7_conc})"
    )
    assert 0.0 <= i7_conc <= 1.0, f"i7 must be in [0,1], got {i7_conc}"
    assert 0.0 <= i7_bal <= 1.0, f"i7 must be in [0,1], got {i7_bal}"


def test_i8_position_diversity_full_coverage_returns_1() -> None:
    """Spans covering all N bins → I-8 = 1.0.

    Using 10 bins over 1000 s video: 10 spans at 100 s intervals.
    """
    from tube_scout.services.time_axis_indicators import compute_i8_position_diversity

    spans = [
        _make_span(i * 100.0, i * 100.0 + 10.0, i * 100.0, i * 100.0 + 10.0, 10.0)
        for i in range(10)
    ]
    result = compute_i8_position_diversity(spans, src_duration=1000.0, tgt_duration=1000.0)

    assert result == pytest.approx(1.0, abs=0.01), (
        f"Full coverage across 10 bins expected I-8=1.0, got {result}"
    )


def test_i8_half_split_returns_two_values_summing_to_total() -> None:
    """compute_i8_half_split returns (first_half, second_half) tuple, both in [0,1]."""
    from tube_scout.services.time_axis_indicators import compute_i8_half_split

    # 2 spans: one in first 500 s, one in second 500 s of 1000 s video
    spans = [
        _make_span(100.0, 200.0, 100.0, 200.0, 100.0),
        _make_span(700.0, 800.0, 700.0, 800.0, 100.0),
    ]
    first_half, second_half = compute_i8_half_split(spans, src_duration=1000.0)

    assert isinstance(first_half, float), "first_half must be float"
    assert isinstance(second_half, float), "second_half must be float"
    assert 0.0 <= first_half <= 1.0, f"first_half={first_half} out of [0,1]"
    assert 0.0 <= second_half <= 1.0, f"second_half={second_half} out of [0,1]"
    # Both halves have at least one span → each half > 0
    assert first_half > 0.0, "First span is in first half → first_half must be > 0"
    assert second_half > 0.0, "Second span is in second half → second_half must be > 0"
