"""Adversary tests for title parser edge cases (T023)."""

import pytest

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.services.title_parser import TitleParser


@pytest.fixture
def parser() -> TitleParser:
    """Create a TitleParser instance."""
    return TitleParser()


class TestEnglishOnlyTitles:
    """Titles entirely in English with no Korean structure."""

    def test_english_title_does_not_crash(self, parser: TitleParser) -> None:
        result = parser.parse(
            "Introduction to Nursing Ethics - Week 3 Session 1", "vid016"
        )
        assert isinstance(result, ParsedTitle)
        assert result.parse_error is True
        expected = "Introduction to Nursing Ethics - Week 3 Session 1"
        assert result.original_title == expected

    def test_english_title_preserves_video_id(self, parser: TitleParser) -> None:
        result = parser.parse("Some Random English Title", "eng001")
        assert result.video_id == "eng001"
        assert result.parse_error is True


class TestEmojiInTitles:
    """Titles containing emoji characters."""

    def test_emoji_does_not_crash(self, parser: TitleParser) -> None:
        title = "홍길동 2024 간호학과 인체구조와기능 🎓 4주차 2차시"
        result = parser.parse(title, "emo001")
        assert isinstance(result, ParsedTitle)
        assert result.week == 4
        assert result.session == 2

    def test_emoji_only_title(self, parser: TitleParser) -> None:
        result = parser.parse("🎓🏥📚", "emo002")
        assert result.parse_error is True
        assert isinstance(result, ParsedTitle)


class TestNoWeekInfo:
    """Titles with no week/session information."""

    def test_no_week_no_session(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 2024 간호학과 인체구조와기능", "noweek001")
        assert result.parse_error is True
        assert result.week is None
        assert result.session is None

    def test_course_only(self, parser: TitleParser) -> None:
        result = parser.parse("인체구조와기능", "noweek002")
        assert result.parse_error is True


class TestSpecialLecture:
    """Titles with 특강 keyword."""

    def test_special_lecture_supplementary(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 특강 간호학개론", "spec001")
        assert result.category == "supplementary"
        assert isinstance(result, ParsedTitle)

    def test_special_lecture_with_date(self, parser: TitleParser) -> None:
        result = parser.parse("2024 홍길동 특강 간호윤리", "spec002")
        assert result.category == "supplementary"
        assert result.year == 2024


class TestVeryLongTitles:
    """Extremely long titles."""

    def test_long_title_does_not_crash(self, parser: TitleParser) -> None:
        long_title = "홍길동 2024 간호학과 " + "인체구조와기능" * 50 + " 4주차 2차시"
        result = parser.parse(long_title, "long001")
        assert isinstance(result, ParsedTitle)
        assert result.original_title == long_title

    def test_very_long_random_text(self, parser: TitleParser) -> None:
        long_title = "A" * 5000
        result = parser.parse(long_title, "long002")
        assert result.parse_error is True
        assert isinstance(result, ParsedTitle)


class TestEmptyAndWhitespace:
    """Empty string and whitespace-only titles."""

    def test_whitespace_only(self, parser: TitleParser) -> None:
        result = parser.parse("   ", "ws001")
        assert result.parse_error is True
        assert isinstance(result, ParsedTitle)

    def test_single_character(self, parser: TitleParser) -> None:
        result = parser.parse("A", "sc001")
        assert result.parse_error is True


class TestSpecialCharacters:
    """Titles with unusual characters."""

    def test_underscores_in_session(self, parser: TitleParser) -> None:
        result = parser.parse(
            "2023학년도 2학기 감염미생물학 3주차_2차시_보완영상 (홍길동)", "sp001"
        )
        assert result.category == "supplementary"
        assert isinstance(result, ParsedTitle)

    def test_hyphen_in_session(self, parser: TitleParser) -> None:
        result = parser.parse(
            "25-1. 홍길동 융합헬스케어4.0 1주차 1차시-1 (간호학과)", "sp002"
        )
        assert isinstance(result, ParsedTitle)
        assert result.week == 1
