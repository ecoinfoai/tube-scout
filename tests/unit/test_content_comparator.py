"""Tests for content comparator (5 indicators, suspicion score, grade, pair matching)."""

import pytest

from tube_scout.services.content_comparator import (
    ContentComparator,
    compute_change_rate,
    compute_cosine_similarity,
    compute_duration_diff,
    compute_new_term_count,
    compute_suspicion_score,
    grade_from_score,
    match_comparison_pairs,
)


class TestComputeChangeRate:
    """Tests for text change rate calculation."""

    def test_identical_texts(self) -> None:
        assert compute_change_rate("hello world", "hello world") == pytest.approx(0.0)

    def test_completely_different_texts(self) -> None:
        rate = compute_change_rate("abc", "xyz")
        assert rate == pytest.approx(1.0)

    def test_partial_change(self) -> None:
        rate = compute_change_rate("hello world test", "hello world new")
        assert 0.0 < rate < 1.0

    def test_empty_source(self) -> None:
        assert compute_change_rate("", "something") == pytest.approx(1.0)

    def test_both_empty(self) -> None:
        assert compute_change_rate("", "") == pytest.approx(0.0)


class TestComputeNewTermCount:
    """Tests for new term count calculation."""

    def test_no_new_terms(self) -> None:
        assert compute_new_term_count("hello world", "hello world") == 0

    def test_all_new_terms(self) -> None:
        assert compute_new_term_count("hello world", "foo bar baz") == 3

    def test_some_new_terms(self) -> None:
        count = compute_new_term_count("hello world", "hello world new terms")
        assert count == 2

    def test_empty_target(self) -> None:
        assert compute_new_term_count("hello world", "") == 0


class TestComputeDurationDiff:
    """Tests for duration difference calculation."""

    def test_same_duration(self) -> None:
        assert compute_duration_diff(300.0, 300.0) == pytest.approx(0.0)

    def test_positive_diff(self) -> None:
        assert compute_duration_diff(300.0, 350.0) == pytest.approx(50.0)

    def test_negative_diff_abs(self) -> None:
        assert compute_duration_diff(350.0, 300.0) == pytest.approx(50.0)


class TestComputeCosineSimilarity:
    """Tests for cosine similarity calculation."""

    def test_identical_vectors(self) -> None:
        vec = [1.0, 0.0, 1.0]
        sim = compute_cosine_similarity(vec, vec)
        assert sim == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        sim = compute_cosine_similarity(vec_a, vec_b)
        assert sim == pytest.approx(0.0)

    def test_similar_vectors(self) -> None:
        vec_a = [1.0, 1.0, 0.0]
        vec_b = [1.0, 0.9, 0.1]
        sim = compute_cosine_similarity(vec_a, vec_b)
        assert sim > 0.9

    def test_zero_vector(self) -> None:
        vec_a = [0.0, 0.0]
        vec_b = [1.0, 1.0]
        sim = compute_cosine_similarity(vec_a, vec_b)
        assert sim == pytest.approx(0.0)


class TestComputeSuspicionScore:
    """Tests for composite suspicion score formula."""

    def test_all_suspicious_indicators(self) -> None:
        score = compute_suspicion_score(
            i1_hash_match=True,
            i2_cosine_similarity=1.0,
            i3_change_rate=0.0,
            i4_new_term_count=0,
            i5_duration_diff_seconds=0.0,
        )
        assert score.score == pytest.approx(100.0)
        assert score.grade.value == "critical"

    def test_all_normal_indicators(self) -> None:
        score = compute_suspicion_score(
            i1_hash_match=False,
            i2_cosine_similarity=0.0,
            i3_change_rate=1.0,
            i4_new_term_count=100,
            i5_duration_diff_seconds=600.0,
        )
        assert score.score < 10.0
        assert score.grade.value == "normal"

    def test_grade_thresholds(self) -> None:
        # critical >= 80
        score_critical = compute_suspicion_score(
            i1_hash_match=True, i2_cosine_similarity=0.95,
            i3_change_rate=0.02, i4_new_term_count=0, i5_duration_diff_seconds=5.0,
        )
        assert score_critical.grade.value == "critical"

        # Score should be between 0 and 100
        assert 0.0 <= score_critical.score <= 100.0

    def test_score_contributions_sum_to_score(self) -> None:
        score = compute_suspicion_score(
            i1_hash_match=False, i2_cosine_similarity=0.7,
            i3_change_rate=0.3, i4_new_term_count=5, i5_duration_diff_seconds=30.0,
        )
        total = (
            score.i1_contribution + score.i2_contribution +
            score.i3_contribution + score.i4_contribution + score.i5_contribution
        )
        assert total == pytest.approx(score.score)


class TestGradeFromScore:
    """Tests for grade assignment from score."""

    def test_critical(self) -> None:
        assert grade_from_score(80.0).value == "critical"
        assert grade_from_score(100.0).value == "critical"

    def test_high(self) -> None:
        assert grade_from_score(60.0).value == "high"
        assert grade_from_score(79.9).value == "high"

    def test_moderate(self) -> None:
        assert grade_from_score(40.0).value == "moderate"
        assert grade_from_score(59.9).value == "moderate"

    def test_normal(self) -> None:
        assert grade_from_score(0.0).value == "normal"
        assert grade_from_score(39.9).value == "normal"


class TestMatchComparisonPairs:
    """Tests for comparison pair matching from parsed titles."""

    def test_basic_pair_matching(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v2", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 1
        assert pairs[0]["source_video_id"] == "v1"
        assert pairs[0]["target_video_id"] == "v2"

    def test_no_match_different_course(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v2", "professor": ["Kim"], "course": "Physics", "week": 1, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 0

    def test_no_match_different_professor(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v2", "professor": ["Lee"], "course": "Math", "week": 1, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 0

    def test_parse_error_excluded(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2025, "parse_error": True},
            {"video_id": "v2", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 0

    def test_multiple_pairs(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v2", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2026, "parse_error": False},
            {"video_id": "v3", "professor": ["Kim"], "course": "Math", "week": 2, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v4", "professor": ["Kim"], "course": "Math", "week": 2, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 2

    def test_missing_fields_excluded(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math", "week": None, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v2", "professor": ["Kim"], "course": "Math", "week": None, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 0
