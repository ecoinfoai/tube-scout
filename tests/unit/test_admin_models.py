"""Tests for multi-channel administration models."""

import pytest
from pydantic import ValidationError

from tube_scout.models.config import ChannelRegistration
from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.search import ExcludeRule, SearchFilter, SearchQuery
from tube_scout.models.validation import ValidationFinding


class TestChannelRegistration:
    """Tests for ChannelRegistration model."""

    def test_valid_channel_registration(self) -> None:
        reg = ChannelRegistration(
            alias="간호학과",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            channel_name="부산보건대 간호학과",
            registered_at="2026-04-04T12:00:00",
            last_used_at="2026-04-04T15:30:00",
            token_path="~/.config/tube-scout/tokens/간호학과.json",
        )
        assert reg.alias == "간호학과"
        assert reg.channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert reg.channel_name == "부산보건대 간호학과"
        assert reg.token_path == "~/.config/tube-scout/tokens/간호학과.json"

    def test_alias_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="alias"):
            ChannelRegistration(
                alias="   ",
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                channel_name="부산보건대 간호학과",
                registered_at="2026-04-04T12:00:00",
                last_used_at="2026-04-04T15:30:00",
                token_path="/tokens/test.json",
            )

    def test_alias_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="alias"):
            ChannelRegistration(
                alias="",
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                channel_name="test",
                registered_at="2026-04-04T12:00:00",
                last_used_at="2026-04-04T15:30:00",
                token_path="/tokens/test.json",
            )

    def test_channel_id_must_start_with_uc(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelRegistration(
                alias="간호학과",
                channel_id="ABinvalid",
                channel_name="test",
                registered_at="2026-04-04T12:00:00",
                last_used_at="2026-04-04T15:30:00",
                token_path="/tokens/test.json",
            )

    def test_channel_name_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="channel_name"):
            ChannelRegistration(
                alias="간호학과",
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                channel_name="  ",
                registered_at="2026-04-04T12:00:00",
                last_used_at="2026-04-04T15:30:00",
                token_path="/tokens/test.json",
            )


class TestParsedTitle:
    """Tests for ParsedTitle model."""

    def test_valid_parsed_title(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="홍길동 2026 간호학과 인체구조와기능 4주차 2차시",
            professor=["홍길동"],
            course="인체구조와기능",
            year=2026,
            semester=1,
            week=4,
            session=2,
            department="간호학과",
            category="regular",
            parse_error=False,
            matched_pattern="standard_kr",
        )
        assert pt.video_id == "vid001"
        assert pt.professor == ["홍길동"]
        assert pt.year == 2026
        assert pt.category == "regular"

    def test_video_id_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="video_id"):
            ParsedTitle(
                video_id="",
                original_title="test title",
                professor=[],
                category="regular",
                parse_error=True,
            )

    def test_original_title_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="original_title"):
            ParsedTitle(
                video_id="vid001",
                original_title="  ",
                professor=[],
                category="regular",
                parse_error=True,
            )

    def test_year_range_valid(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="test",
            professor=[],
            year=2024,
            category="regular",
            parse_error=False,
        )
        assert pt.year == 2024

    def test_year_below_2000_rejected(self) -> None:
        with pytest.raises(ValidationError, match="year"):
            ParsedTitle(
                video_id="vid001",
                original_title="test",
                professor=[],
                year=1999,
                category="regular",
                parse_error=False,
            )

    def test_year_above_2099_rejected(self) -> None:
        with pytest.raises(ValidationError, match="year"):
            ParsedTitle(
                video_id="vid001",
                original_title="test",
                professor=[],
                year=2100,
                category="regular",
                parse_error=False,
            )

    def test_year_none_allowed(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="test",
            professor=[],
            category="regular",
            parse_error=True,
        )
        assert pt.year is None

    def test_semester_valid_values(self) -> None:
        for sem in (1, 2):
            pt = ParsedTitle(
                video_id="vid001",
                original_title="test",
                professor=[],
                semester=sem,
                category="regular",
                parse_error=False,
            )
            assert pt.semester == sem

    def test_semester_invalid_rejected(self) -> None:
        with pytest.raises(ValidationError, match="semester"):
            ParsedTitle(
                video_id="vid001",
                original_title="test",
                professor=[],
                semester=3,
                category="regular",
                parse_error=False,
            )

    def test_category_must_be_valid(self) -> None:
        with pytest.raises(ValidationError, match="category"):
            ParsedTitle(
                video_id="vid001",
                original_title="test",
                professor=[],
                category="invalid",
                parse_error=False,
            )

    def test_supplementary_category(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="보완영상",
            professor=[],
            category="supplementary",
            parse_error=False,
        )
        assert pt.category == "supplementary"

    def test_empty_professor_list(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="test",
            professor=[],
            category="regular",
            parse_error=True,
        )
        assert pt.professor == []

    def test_multiple_professors(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="test",
            professor=["홍길동", "김영희"],
            category="regular",
            parse_error=False,
        )
        assert len(pt.professor) == 2

    def test_optional_fields_default_none(self) -> None:
        pt = ParsedTitle(
            video_id="vid001",
            original_title="test",
            professor=[],
            category="regular",
            parse_error=True,
        )
        assert pt.course is None
        assert pt.year is None
        assert pt.semester is None
        assert pt.week is None
        assert pt.session is None
        assert pt.department is None
        assert pt.matched_pattern is None


class TestValidationFinding:
    """Tests for ValidationFinding model."""

    def test_valid_finding(self) -> None:
        f = ValidationFinding(
            rule_id="V-001",
            severity="WARNING",
            video_ids=["vid001"],
            professor="홍길동",
            description="Year mismatch detected",
            details={"expected": 2026, "actual": 2024},
        )
        assert f.rule_id == "V-001"
        assert f.severity == "WARNING"
        assert f.video_ids == ["vid001"]
        assert f.details["expected"] == 2026

    def test_rule_id_must_be_valid_format(self) -> None:
        with pytest.raises(ValidationError, match="rule_id"):
            ValidationFinding(
                rule_id="X-001",
                severity="WARNING",
                video_ids=["vid001"],
                description="test",
                details={},
            )

    def test_rule_id_v009_valid(self) -> None:
        f = ValidationFinding(
            rule_id="V-009",
            severity="INFO",
            video_ids=["vid001"],
            description="Upload gap",
            details={},
        )
        assert f.rule_id == "V-009"

    def test_rule_id_v010_rejected(self) -> None:
        with pytest.raises(ValidationError, match="rule_id"):
            ValidationFinding(
                rule_id="V-010",
                severity="INFO",
                video_ids=["vid001"],
                description="test",
                details={},
            )

    def test_severity_must_be_valid(self) -> None:
        with pytest.raises(ValidationError, match="severity"):
            ValidationFinding(
                rule_id="V-001",
                severity="CRITICAL",
                video_ids=["vid001"],
                description="test",
                details={},
            )

    def test_all_severity_levels(self) -> None:
        for sev in ("ERROR", "WARNING", "INFO"):
            f = ValidationFinding(
                rule_id="V-001",
                severity=sev,
                video_ids=["vid001"],
                description="test",
                details={},
            )
            assert f.severity == sev

    def test_video_ids_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError, match="video_ids"):
            ValidationFinding(
                rule_id="V-001",
                severity="WARNING",
                video_ids=[],
                description="test",
                details={},
            )

    def test_description_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="description"):
            ValidationFinding(
                rule_id="V-001",
                severity="WARNING",
                video_ids=["vid001"],
                description="  ",
                details={},
            )

    def test_professor_optional(self) -> None:
        f = ValidationFinding(
            rule_id="V-003",
            severity="ERROR",
            video_ids=["vid001"],
            description="Invalid week",
            details={},
        )
        assert f.professor is None


class TestSearchFilter:
    """Tests for SearchFilter model."""

    def test_valid_search_filter(self) -> None:
        sf = SearchFilter(
            professor="홍길동",
            course="감염미생물학",
            year=2024,
            semester=2,
            week_range=[1, 8],
            session=1,
        )
        assert sf.professor == "홍길동"
        assert sf.week_range == [1, 8]

    def test_all_optional_fields(self) -> None:
        sf = SearchFilter()
        assert sf.professor is None
        assert sf.course is None
        assert sf.year is None
        assert sf.semester is None
        assert sf.week_range is None
        assert sf.session is None

    def test_semester_must_be_1_or_2(self) -> None:
        with pytest.raises(ValidationError, match="semester"):
            SearchFilter(semester=3)

    def test_week_range_must_have_two_elements(self) -> None:
        with pytest.raises(ValidationError, match="week_range"):
            SearchFilter(week_range=[1])

    def test_week_range_start_must_be_lte_end(self) -> None:
        with pytest.raises(ValidationError, match="week_range"):
            SearchFilter(week_range=[8, 1])


class TestExcludeRule:
    """Tests for ExcludeRule model."""

    def test_valid_exclude_rule(self) -> None:
        er = ExcludeRule(title_contains=["질문응답", "보완영상"])
        assert len(er.title_contains) == 2

    def test_default_empty_list(self) -> None:
        er = ExcludeRule()
        assert er.title_contains == []


class TestSearchQuery:
    """Tests for SearchQuery model."""

    def test_valid_search_query_with_filter(self) -> None:
        sq = SearchQuery(
            filters=SearchFilter(professor="홍길동", year=2024),
        )
        assert sq.filters is not None
        assert sq.filters.professor == "홍길동"

    def test_valid_search_query_with_queries(self) -> None:
        sq = SearchQuery(
            queries=[
                SearchFilter(professor="홍길동", course="감염미생물학"),
                SearchFilter(professor="홍길동", course="인체구조와기능"),
            ],
        )
        assert len(sq.queries) == 2

    def test_valid_search_query_with_exclude(self) -> None:
        sq = SearchQuery(
            filters=SearchFilter(professor="홍길동"),
            exclude=ExcludeRule(title_contains=["OT"]),
        )
        assert sq.exclude is not None
        assert sq.exclude.title_contains == ["OT"]

    def test_defaults(self) -> None:
        sq = SearchQuery()
        assert sq.filters is None
        assert sq.queries == []
        assert sq.exclude is None
