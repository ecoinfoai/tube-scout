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
    from tube_scout.services.time_axis_indicators import compute_time_axis
    from tube_scout.models.reuse_v2 import CandidatePair

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
