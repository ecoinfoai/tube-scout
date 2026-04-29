"""Adversary tests for content reuse detection edge cases.

Tests malformed data, boundary conditions, and failure scenarios
for the fingerprint, comparator, quality checker, and SRT parser.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tube_scout.services.content_comparator import (
    compute_change_rate,
    compute_cosine_similarity,
    compute_new_term_count,
    compute_suspicion_score,
    match_comparison_pairs,
)
from tube_scout.services.fingerprint import FingerprintService
from tube_scout.services.quality_checker import QualityChecker
from tube_scout.services.srt_parser import parse_srt
from tube_scout.storage.content_db import ContentDB


class TestEmptyCaptions:
    """Edge cases with empty or missing captions."""

    def test_fingerprint_empty_segments(self) -> None:
        service = FingerprintService()
        with pytest.raises(ValueError, match="segments must not be empty"):
            service.generate_hash([])

    def test_fingerprint_whitespace_only_segments(self) -> None:
        service = FingerprintService()
        # Segments with only whitespace text
        segments = [{"text": "   ", "start": 0.0, "duration": 1.0}]
        # Should still hash (empty after strip, but joined text is empty)
        fp = service.generate_hash(segments)
        assert fp.full_text_length == 0

    def test_quality_check_no_segments(self) -> None:
        checker = QualityChecker()
        result = checker.run_all_checks(segments=None, duration_seconds=600)
        assert result.q001_voice_present is False
        assert result.q003_course_relevance is None
        assert result.q004_silence_ratio is None
        assert result.q005_speech_density is None


class TestSingleVideoCourse:
    """Edge case: course with only one video (no pair possible)."""

    def test_no_pair_for_single_year(self) -> None:
        titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math",
             "week": 1, "session": 1, "year": 2025, "parse_error": False},
        ]
        pairs = match_comparison_pairs(titles, year_from=2025, year_to=2026)
        assert len(pairs) == 0


class TestIdenticalHashPair:
    """Edge case: videos with identical hashes."""

    def test_identical_hash_full_suspicion(self) -> None:
        score = compute_suspicion_score(
            i1_hash_match=True,
            i2_cosine_similarity=1.0,
            i3_change_rate=0.0,
            i4_new_term_count=0,
            i5_duration_diff_seconds=0.0,
        )
        assert score.score == pytest.approx(100.0)
        assert score.grade.value == "critical"


class TestCosineSimilarityEdgeCases:
    """Edge cases for cosine similarity computation."""

    def test_zero_zero_vectors(self) -> None:
        sim = compute_cosine_similarity([0.0, 0.0], [0.0, 0.0])
        assert sim == pytest.approx(0.0)

    def test_identical_unit_vectors(self) -> None:
        sim = compute_cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert sim == pytest.approx(1.0)

    def test_opposite_vectors(self) -> None:
        sim = compute_cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        # Clamped to 0.0
        assert sim == pytest.approx(0.0)

    def test_single_dimension(self) -> None:
        sim = compute_cosine_similarity([5.0], [5.0])
        assert sim == pytest.approx(1.0)


class TestMalformedSRT:
    """Edge cases for SRT parsing."""

    def test_only_numbers(self) -> None:
        segments = parse_srt("1\n2\n3\n")
        assert segments == []

    def test_timestamp_without_text(self) -> None:
        srt = "1\n00:00:00,000 --> 00:00:01,000\n\n"
        segments = parse_srt(srt)
        assert len(segments) == 0

    def test_very_long_text(self) -> None:
        long_text = "word " * 10000
        srt = f"1\n00:00:00,000 --> 00:01:00,000\n{long_text}\n\n"
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert len(segments[0]["text"]) > 0

    def test_negative_duration(self) -> None:
        # End time before start time
        srt = "1\n00:00:05,000 --> 00:00:01,000\nBackwards\n\n"
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0]["duration"] < 0  # Should still parse, caller decides

    def test_mixed_valid_invalid_blocks(self) -> None:
        srt = (
            "1\nINVALID\nText1\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nValid\n\n"
            "3\nALSO INVALID\nText3\n\n"
        )
        segments = parse_srt(srt)
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid"


class TestConcurrentDBAccess:
    """Edge cases for SQLite concurrent access patterns."""

    def test_multiple_inserts_same_video(self, tmp_path: Path) -> None:
        db = ContentDB(tmp_path / "test.db")
        db.upsert_processing_status("v1", "c1", "pending")
        db.upsert_processing_status("v1", "c1", "collecting")
        db.upsert_processing_status("v1", "c1", "collected")
        result = db.get_processing_status("v1")
        assert result is not None
        assert result["status"] == "collected"

    def test_duplicate_comparison_pair(self, tmp_path: Path) -> None:
        db = ContentDB(tmp_path / "test.db")
        db.insert_comparison(
            source_video_id="v1", target_video_id="v2",
            professor="Kim", course="Math", week=1, session=1,
            year_from=2025, year_to=2026,
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_comparison(
                source_video_id="v1", target_video_id="v2",
                professor="Kim", course="Math", week=1, session=1,
                year_from=2025, year_to=2026,
            )


class TestChangeRateEdgeCases:
    """Edge cases for text change rate."""

    def test_unicode_text(self) -> None:
        rate = compute_change_rate(
            "안녕하세요 반갑습니다",
            "안녕하세요 반갑습니다",
        )
        assert rate == pytest.approx(0.0)

    def test_very_long_text(self) -> None:
        text = "word " * 10000
        rate = compute_change_rate(text, text)
        assert rate == pytest.approx(0.0)

    def test_one_word_change(self) -> None:
        rate = compute_change_rate("hello world foo", "hello world bar")
        assert 0.0 < rate < 1.0


class TestNewTermCountEdgeCases:
    """Edge cases for new term count."""

    def test_empty_source_and_target(self) -> None:
        assert compute_new_term_count("", "") == 0

    def test_duplicate_terms_in_target(self) -> None:
        # "new new" has 1 unique new term
        count = compute_new_term_count("old", "old new new")
        assert count == 1


class TestSuspicionScoreEdgeCases:
    """Edge cases for suspicion score formula."""

    def test_all_zeros(self) -> None:
        score = compute_suspicion_score(
            i1_hash_match=False,
            i2_cosine_similarity=0.0,
            i3_change_rate=0.0,
            i4_new_term_count=0,
            i5_duration_diff_seconds=0.0,
        )
        # Low change rate means high suspicion for i3
        # 0 new terms means high suspicion for i4
        # 0 duration diff means high suspicion for i5
        assert score.score > 0.0

    def test_max_new_terms(self) -> None:
        score = compute_suspicion_score(
            i1_hash_match=False,
            i2_cosine_similarity=0.0,
            i3_change_rate=1.0,
            i4_new_term_count=10000,
            i5_duration_diff_seconds=10000.0,
        )
        assert score.score < 5.0
        assert score.grade.value == "normal"
