"""Tests for title parser service (T022, T031)."""

import json
from pathlib import Path

import pytest

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.services.title_parser import TitleParser


@pytest.fixture
def parser() -> TitleParser:
    """Create a TitleParser instance."""
    return TitleParser()


@pytest.fixture
def sample_titles() -> list[dict]:
    """Load sample titles from fixture."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_titles.json"
    with open(fixture_path) as f:
        return json.load(f)


class TestStandardKrPattern:
    """Tests for pattern 1: professor year department course N-week M-session."""

    def test_full_match(self, parser: TitleParser) -> None:
        title = "홍길동 2026 간호학과 인체구조와기능 4주차 2차시"
        result = parser.parse(title, "vid001")
        assert result.professor == ["홍길동"]
        assert result.year == 2026
        assert result.department == "간호학과"
        assert result.course == "인체구조와기능"
        assert result.week == 4
        assert result.session == 2
        assert result.matched_pattern == "standard_kr"
        assert result.parse_error is False

    def test_without_department(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 2024 감염미생물학 5주차 1차시", "vid010")
        assert result.professor == ["홍길동"]
        assert result.year == 2024
        assert result.course == "감염미생물학"
        assert result.week == 5
        assert result.session == 1
        assert result.parse_error is False

    def test_different_department(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 2024 물리치료과 기능해부학 2주차 1차시", "vid025")
        assert result.professor == ["홍길동"]
        assert result.department == "물리치료과"
        assert result.course == "기능해부학"
        assert result.week == 2
        assert result.session == 1


class TestSemesterExplicitPattern:
    """Tests for pattern 2: course year N-semester professor N-week M-session."""

    def test_full_match(self, parser: TitleParser) -> None:
        result = parser.parse("감염미생물학 2024 2학기 홍길동 2주차 1차시", "vid002")
        assert result.course == "감염미생물학"
        assert result.year == 2024
        assert result.semester == 2
        assert result.professor == ["홍길동"]
        assert result.week == 2
        assert result.session == 1
        assert result.matched_pattern == "semester_explicit"
        assert result.parse_error is False

    def test_semester_1(self, parser: TitleParser) -> None:
        title = "감염미생물학 2024 1학기 홍길동/김영수 8주차 2차시"
        result = parser.parse(title, "vid024")
        assert result.semester == 1
        assert result.professor == ["홍길동", "김영수"]
        assert result.week == 8
        assert result.session == 2


class TestCoTeachingPattern:
    """Tests for co-teaching pattern."""

    def test_full_match(self, parser: TitleParser) -> None:
        result = parser.parse(
            "24-1/25-1 홍길동/김영희 융합헬스케어4.0 3주차 1차시 (간호학과)", "vid003"
        )
        assert result.professor == ["홍길동", "김영희"]
        assert result.course == "융합헬스케어4.0"
        assert result.week == 3
        assert result.session == 1
        assert result.department == "간호학과"
        assert result.matched_pattern == "co_teaching"
        assert result.parse_error is False


class TestAcademicYearPattern:
    """Tests for pattern 4: academic-year N-semester course N-week (professor)."""

    def test_full_match(self, parser: TitleParser) -> None:
        result = parser.parse("2023학년도 2학기 국어 5주차 (홍길동)", "vid004")
        assert result.year == 2023
        assert result.semester == 2
        assert result.course == "국어"
        assert result.week == 5
        assert result.professor == ["홍길동"]
        assert result.matched_pattern == "academic_year"
        assert result.parse_error is False

    def test_with_session_suffix(self, parser: TitleParser) -> None:
        result = parser.parse("2023학년도 2학기 감염미생물학 14주차 (홍길동)", "vid009")
        assert result.year == 2023
        assert result.week == 14
        assert result.course == "감염미생물학"


class TestNumberedPrefixPattern:
    """Tests for pattern 5: number.professor course N-week M-session (department)."""

    def test_full_match(self, parser: TitleParser) -> None:
        result = parser.parse(
            "5-1.홍길동 인체구조와기능 1주차 1차시(간호학과)", "vid015"
        )
        assert result.professor == ["홍길동"]
        assert result.course == "인체구조와기능"
        assert result.week == 1
        assert result.session == 1
        assert result.department == "간호학과"
        assert result.matched_pattern == "numbered_prefix"
        assert result.parse_error is False

    def test_with_session_suffix(self, parser: TitleParser) -> None:
        result = parser.parse(
            "25-1. 홍길동 융합헬스케어4.0 1주차 1차시-1 (간호학과)", "vid005"
        )
        assert result.professor == ["홍길동"]
        assert result.course is not None
        assert result.week == 1


class TestFallbackParsing:
    """Tests for fallback parsing when no full pattern matches."""

    def test_extracts_week_only(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 인체해부연수 1차시 (간호학과)", "vid006")
        assert result.parse_error is True
        has_partial = (
            result.session == 1
            or result.week is not None
            or result.professor == ["홍길동"]
        )
        assert has_partial

    def test_extracts_partial_fields(self, parser: TitleParser) -> None:
        result = parser.parse("2024 홍길동 국어 6주차 강의영상", "vid011")
        assert result.week == 6
        assert result.year == 2024
        # Professor may or may not be extracted in fallback

    def test_unparseable_preserves_original(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동", "vid022")
        assert result.original_title == "홍길동"
        assert result.parse_error is True
        assert result.video_id == "vid022"

    def test_korean_suffix_not_treated_as_professor(self, parser: TitleParser) -> None:
        """L-08: Korean academic suffixes should not be extracted as professor names."""
        result = parser.parse("3주차 강의", "vid_suffix")
        assert "주차" not in result.professor

        result2 = parser.parse("차시 복습영상", "vid_suffix2")
        assert "차시" not in result2.professor

        result3 = parser.parse("학과 소개 영상", "vid_suffix3")
        assert "학과" not in result3.professor

    def test_semester_year_prefix(self, parser: TitleParser) -> None:
        result = parser.parse(
            "2025-1 홍길동 간호학과 인체구조와기능 15주차 2차시 기말정리", "vid023"
        )
        assert result.week == 15
        assert result.session == 2


class TestMultiProfessor:
    """Tests for multi-professor extraction."""

    def test_slash_separated(self, parser: TitleParser) -> None:
        result = parser.parse(
            "24-1/25-1 홍길동/김영희 융합헬스케어4.0 3주차 1차시 (간호학과)", "vid003"
        )
        assert result.professor == ["홍길동", "김영희"]

    def test_parenthesized_professor(self, parser: TitleParser) -> None:
        result = parser.parse("2023학년도 2학기 국어 5주차 (홍길동)", "vid004")
        assert result.professor == ["홍길동"]

    def test_slash_in_semester_explicit(self, parser: TitleParser) -> None:
        title = "감염미생물학 2024 1학기 홍길동/김영수 8주차 2차시"
        result = parser.parse(title, "vid024")
        assert result.professor == ["홍길동", "김영수"]


class TestSupplementaryClassification:
    """Tests for supplementary video classification."""

    def test_regular_video(self, parser: TitleParser) -> None:
        title = "홍길동 2026 간호학과 인체구조와기능 4주차 2차시"
        result = parser.parse(title, "vid001")
        assert result.category == "regular"

    def test_qa_video(self, parser: TitleParser) -> None:
        result = parser.parse(
            "2023 감염미생물학 4주차 2차시 질문응답 (홍길동)", "vid013"
        )
        assert result.category == "supplementary"

    def test_supplementary_video(self, parser: TitleParser) -> None:
        result = parser.parse(
            "2023학년도 2학기 감염미생물학 3주차_2차시_보완영상 (홍길동)", "vid014"
        )
        assert result.category == "supplementary"

    def test_key_video(self, parser: TitleParser) -> None:
        result = parser.parse("2025 홍길동 핵심영상 감염미생물학 7주차", "vid019")
        assert result.category == "supplementary"

    def test_supplement_video(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 2024 감염미생물학 보충 3주차", "vid020")
        assert result.category == "supplementary"

    def test_ot_video(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 2024 간호학과 인체구조와기능 OT", "vid018")
        assert result.category == "supplementary"

    def test_special_lecture(self, parser: TitleParser) -> None:
        result = parser.parse("홍길동 특강 간호학개론", "vid017")
        assert result.category == "supplementary"


class TestParseBatch:
    """Tests for parse_batch method with summary stats."""

    def test_batch_returns_list(self, parser: TitleParser) -> None:
        t1 = "홍길동 2026 간호학과 인체구조와기능 4주차 2차시"
        t2 = "감염미생물학 2024 2학기 홍길동 2주차 1차시"
        videos = [
            {"video_id": "v1", "title": t1},
            {"video_id": "v2", "title": t2},
        ]
        results, stats = parser.parse_batch(videos)
        assert len(results) == 2
        assert all(isinstance(r, ParsedTitle) for r in results)

    def test_batch_stats(self, parser: TitleParser) -> None:
        t1 = "홍길동 2026 간호학과 인체구조와기능 4주차 2차시"
        videos = [
            {"video_id": "v1", "title": t1},
            {"video_id": "v2", "title": "unparseable gibberish"},
        ]
        results, stats = parser.parse_batch(videos)
        assert stats["total"] == 2
        assert stats["success_count"] >= 1
        assert stats["error_count"] >= 0
        assert stats["success_count"] + stats["error_count"] == stats["total"]
        assert 0.0 <= stats["success_rate"] <= 1.0

    def test_batch_empty(self, parser: TitleParser) -> None:
        results, stats = parser.parse_batch([])
        assert results == []
        assert stats["total"] == 0
        assert stats["success_count"] == 0
        assert stats["error_count"] == 0
        assert stats["success_rate"] == 0.0


class TestSampleTitlesSuccessRate:
    """T031: Verify ≥85% success rate on sample titles fixture."""

    def test_success_rate_at_least_85_percent(
        self, parser: TitleParser, sample_titles: list[dict]
    ) -> None:
        # Filter out empty titles (vid021) which are expected to fail validation
        valid_titles = [t for t in sample_titles if t["title"].strip()]
        results, stats = parser.parse_batch(valid_titles)
        assert stats["success_rate"] >= 0.85, (
            f"Success rate {stats['success_rate']:.2%} is below 85%. "
            f"Errors: {stats['error_count']}/{stats['total']}"
        )
