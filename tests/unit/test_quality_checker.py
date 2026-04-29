"""Tests for quality checker service (Q-001~Q-005)."""

import pytest

from tube_scout.services.quality_checker import QualityChecker, QualityResult


class TestQualityCheckerVoicePresence:
    """Tests for Q-001: voice presence check."""

    def test_has_captions_passes(self) -> None:
        checker = QualityChecker()
        segments = [{"text": "hello", "start": 0.0, "duration": 3.0}]
        result = checker.check_voice_presence(segments)
        assert result is True

    def test_no_captions_fails(self) -> None:
        checker = QualityChecker()
        result = checker.check_voice_presence(None)
        assert result is False

    def test_empty_segments_fails(self) -> None:
        checker = QualityChecker()
        result = checker.check_voice_presence([])
        assert result is False


class TestQualityCheckerMinDuration:
    """Tests for Q-002: minimum duration check."""

    def test_above_threshold_passes(self) -> None:
        checker = QualityChecker()
        assert checker.check_min_duration(600) is True  # 10 min

    def test_exactly_threshold_passes(self) -> None:
        checker = QualityChecker()
        assert checker.check_min_duration(300) is True  # 5 min

    def test_below_threshold_fails(self) -> None:
        checker = QualityChecker()
        assert checker.check_min_duration(299) is False

    def test_custom_threshold(self) -> None:
        checker = QualityChecker(min_duration_seconds=600)
        assert checker.check_min_duration(599) is False
        assert checker.check_min_duration(600) is True


class TestQualityCheckerCourseRelevance:
    """Tests for Q-003: course relevance check."""

    def test_relevant_text(self) -> None:
        checker = QualityChecker()
        segments = [
            {"text": "오늘은 해부학 근육 구조를 학습하겠습니다", "start": 0.0, "duration": 5.0},
        ]
        relevance = checker.check_course_relevance(segments, course_name="해부학")
        assert relevance is not None
        assert relevance > 0.0

    def test_no_course_name(self) -> None:
        checker = QualityChecker()
        segments = [{"text": "test", "start": 0.0, "duration": 1.0}]
        relevance = checker.check_course_relevance(segments, course_name=None)
        assert relevance is None

    def test_empty_segments(self) -> None:
        checker = QualityChecker()
        relevance = checker.check_course_relevance([], course_name="Math")
        assert relevance is None


class TestQualityCheckerSilenceRatio:
    """Tests for Q-004: silence ratio check."""

    def test_no_silence(self) -> None:
        checker = QualityChecker()
        segments = [
            {"text": "continuous", "start": 0.0, "duration": 10.0},
        ]
        ratio = checker.check_silence_ratio(segments, total_duration=10.0)
        assert ratio is not None
        assert ratio == pytest.approx(0.0)

    def test_half_silence(self) -> None:
        checker = QualityChecker()
        segments = [
            {"text": "first part", "start": 0.0, "duration": 5.0},
            {"text": "second part", "start": 10.0, "duration": 5.0},
        ]
        ratio = checker.check_silence_ratio(segments, total_duration=20.0)
        assert ratio is not None
        assert ratio == pytest.approx(0.5)

    def test_empty_segments(self) -> None:
        checker = QualityChecker()
        ratio = checker.check_silence_ratio([], total_duration=100.0)
        assert ratio is None

    def test_zero_duration(self) -> None:
        checker = QualityChecker()
        ratio = checker.check_silence_ratio(
            [{"text": "x", "start": 0.0, "duration": 1.0}],
            total_duration=0.0,
        )
        assert ratio is None


class TestQualityCheckerSpeechDensity:
    """Tests for Q-005: speech density check."""

    def test_normal_density(self) -> None:
        checker = QualityChecker()
        # 1000 chars in 5 minutes = 200 chars/min
        segments = [{"text": "a" * 1000, "start": 0.0, "duration": 300.0}]
        density = checker.check_speech_density(segments, total_duration=300.0)
        assert density is not None
        assert density == pytest.approx(200.0)

    def test_empty_segments(self) -> None:
        checker = QualityChecker()
        density = checker.check_speech_density([], total_duration=300.0)
        assert density is None

    def test_zero_duration(self) -> None:
        checker = QualityChecker()
        density = checker.check_speech_density(
            [{"text": "hello", "start": 0.0, "duration": 1.0}],
            total_duration=0.0,
        )
        assert density is None


class TestQualityCheckerRunAll:
    """Tests for running all checks together."""

    def test_all_pass(self) -> None:
        checker = QualityChecker()
        segments = [
            {"text": "해부학 관련 내용 " * 100, "start": 0.0, "duration": 300.0},
        ]
        result = checker.run_all_checks(
            segments=segments,
            duration_seconds=600,
            course_name="해부학",
        )
        assert isinstance(result, QualityResult)
        assert result.q001_voice_present is True
        assert result.q002_min_duration is True
        assert result.pass_count >= 2

    def test_no_captions(self) -> None:
        checker = QualityChecker()
        result = checker.run_all_checks(
            segments=None,
            duration_seconds=600,
            course_name="Math",
        )
        assert result.q001_voice_present is False
        assert result.pass_count <= 1  # Only duration might pass

    def test_short_video(self) -> None:
        checker = QualityChecker()
        segments = [{"text": "short", "start": 0.0, "duration": 60.0}]
        result = checker.run_all_checks(
            segments=segments,
            duration_seconds=60,
        )
        assert result.q002_min_duration is False
