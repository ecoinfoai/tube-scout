"""Tests for structured search service."""

import time
from pathlib import Path

import pytest

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.search import ExcludeRule, SearchFilter, SearchQuery
from tube_scout.services.search_service import SearchService


@pytest.fixture()
def sample_titles() -> list[ParsedTitle]:
    """Create a list of parsed titles for testing."""
    return [
        ParsedTitle(
            video_id="vid001",
            original_title="홍길동 2024 감염미생물학 5주차 1차시",
            professor=["홍길동"],
            course="감염미생물학",
            year=2024,
            semester=2,
            week=5,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid002",
            original_title="홍길동 2024 간호학과 인체구조와기능 4주차 2차시",
            professor=["홍길동"],
            course="인체구조와기능",
            year=2024,
            semester=1,
            week=4,
            session=2,
            department="간호학과",
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid003",
            original_title="김영희 2024 융합헬스케어4.0 3주차 1차시",
            professor=["김영희"],
            course="융합헬스케어4.0",
            year=2024,
            semester=1,
            week=3,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid004",
            original_title="홍길동 2025 감염미생물학 13주차 1차시",
            professor=["홍길동"],
            course="감염미생물학",
            year=2025,
            semester=1,
            week=13,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid005",
            original_title="2023 감염미생물학 4주차 2차시 질문응답 (홍길동)",
            professor=["홍길동"],
            course="감염미생물학",
            year=2023,
            semester=2,
            week=4,
            session=2,
            category="supplementary",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid006",
            original_title="홍길동 2024 간호학과 인체구조와기능 OT",
            professor=["홍길동"],
            course="인체구조와기능",
            year=2024,
            semester=1,
            week=None,
            session=None,
            department="간호학과",
            category="supplementary",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid007",
            original_title="홍길동/김영희 융합헬스케어4.0 3주차 1차시",
            professor=["홍길동", "김영희"],
            course="융합헬스케어4.0",
            year=2024,
            semester=1,
            week=3,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid008",
            original_title="홍길동 2024 감염미생물학 보완영상 3주차",
            professor=["홍길동"],
            course="감염미생물학",
            year=2024,
            semester=2,
            week=3,
            session=None,
            category="supplementary",
            parse_error=False,
        ),
    ]


class TestSearchServiceSingleFilter:
    """Tests for single AND filter search."""

    def test_filter_by_professor(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(professor="홍길동"))
        results = SearchService.search(sample_titles, query)
        assert all("홍길동" in pt.professor for pt in results)
        assert len(results) == 7

    def test_filter_by_course(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(course="감염미생물학"))
        results = SearchService.search(sample_titles, query)
        assert all(pt.course == "감염미생물학" for pt in results)
        assert len(results) == 4

    def test_filter_by_year(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(year=2024))
        results = SearchService.search(sample_titles, query)
        assert all(pt.year == 2024 for pt in results)
        assert len(results) == 6

    def test_filter_by_semester(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(semester=2))
        results = SearchService.search(sample_titles, query)
        assert all(pt.semester == 2 for pt in results)
        assert len(results) == 3

    def test_filter_by_session(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(session=1))
        results = SearchService.search(sample_titles, query)
        assert all(pt.session == 1 for pt in results)
        assert len(results) == 4

    def test_filter_and_logic(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(
            filters=SearchFilter(professor="홍길동", course="감염미생물학", year=2024)
        )
        results = SearchService.search(sample_titles, query)
        assert len(results) == 2
        assert all(
            "홍길동" in pt.professor and pt.course == "감염미생물학" and pt.year == 2024
            for pt in results
        )

    def test_filter_by_week_range(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(week_range=[3, 5]))
        results = SearchService.search(sample_titles, query)
        assert all(pt.week is not None and 3 <= pt.week <= 5 for pt in results)
        assert len(results) == 6

    def test_partial_match_professor(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(professor="정광"))
        results = SearchService.search(sample_titles, query)
        assert len(results) == 7  # "홍길동" contains "정광"

    def test_partial_match_course(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(course="감염"))
        results = SearchService.search(sample_titles, query)
        assert len(results) == 4  # "감염미생물학" contains "감염"


class TestSearchServiceOrQueries:
    """Tests for OR-combined query groups."""

    def test_or_queries(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(
            queries=[
                SearchFilter(course="감염미생물학", year=2024),
                SearchFilter(course="인체구조와기능", year=2024),
            ]
        )
        results = SearchService.search(sample_titles, query)
        video_ids = {pt.video_id for pt in results}
        assert "vid001" in video_ids  # 감염미생물학 2024
        assert "vid002" in video_ids  # 인체구조와기능 2024
        assert "vid008" in video_ids  # 감염미생물학 2024 보완영상

    def test_or_queries_deduplicate(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(
            queries=[
                SearchFilter(professor="홍길동", year=2024),
                SearchFilter(course="감염미생물학", year=2024),
            ]
        )
        results = SearchService.search(sample_titles, query)
        video_ids = [pt.video_id for pt in results]
        # No duplicates
        assert len(video_ids) == len(set(video_ids))


class TestSearchServiceExclude:
    """Tests for exclusion rules."""

    def test_exclude_by_title_keyword(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(
            filters=SearchFilter(professor="홍길동"),
            exclude=ExcludeRule(title_contains=["질문응답"]),
        )
        results = SearchService.search(sample_titles, query)
        assert all("질문응답" not in pt.original_title for pt in results)
        assert "vid005" not in {pt.video_id for pt in results}

    def test_exclude_multiple_keywords(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(
            filters=SearchFilter(professor="홍길동"),
            exclude=ExcludeRule(title_contains=["질문응답", "보완영상", "OT"]),
        )
        results = SearchService.search(sample_titles, query)
        video_ids = {pt.video_id for pt in results}
        assert "vid005" not in video_ids  # 질문응답
        assert "vid006" not in video_ids  # OT
        assert "vid008" not in video_ids  # 보완영상


class TestSearchServiceEmptyResults:
    """Tests for empty results."""

    def test_no_match_returns_empty(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery(filters=SearchFilter(professor="존재하지않는교수"))
        results = SearchService.search(sample_titles, query)
        assert results == []

    def test_empty_titles_returns_empty(self) -> None:
        query = SearchQuery(filters=SearchFilter(professor="홍길동"))
        results = SearchService.search([], query)
        assert results == []

    def test_empty_query_returns_all(self, sample_titles: list[ParsedTitle]) -> None:
        query = SearchQuery()
        results = SearchService.search(sample_titles, query)
        assert len(results) == len(sample_titles)


class TestSearchServiceLoadConfig:
    """Tests for YAML config loading."""

    def test_load_sample_config(self) -> None:
        fixtures = Path(__file__).parent.parent / "fixtures"
        yaml_path = fixtures / "search_clips_sample.yaml"
        query = SearchService.load_config(yaml_path)
        assert query.filters is not None
        assert query.filters.professor == "홍길동"
        assert query.filters.year == 2024
        assert query.filters.semester == 2
        assert len(query.queries) == 2
        assert query.exclude is not None
        assert "질문응답" in query.exclude.title_contains

    def test_load_minimal_config(self, tmp_path: Path) -> None:
        config = tmp_path / "minimal.yaml"
        config.write_text("filters:\n  professor: '홍길동'\n", encoding="utf-8")
        query = SearchService.load_config(config)
        assert query.filters is not None
        assert query.filters.professor == "홍길동"
        assert query.queries == []
        assert query.exclude is None

    def test_load_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            SearchService.load_config(Path("/nonexistent/config.yaml"))

    def test_load_invalid_yaml_raises(self, tmp_path: Path) -> None:
        config = tmp_path / "bad.yaml"
        config.write_text("{{not valid yaml", encoding="utf-8")
        with pytest.raises(ValueError, match="parse"):
            SearchService.load_config(config)


class TestSearchServiceCliConversion:
    """Tests for CLI flags to SearchQuery conversion."""

    def test_cli_professor_only(self) -> None:
        query = SearchService.from_cli_flags(professor="홍길동")
        assert query.filters is not None
        assert query.filters.professor == "홍길동"

    def test_cli_all_flags(self) -> None:
        query = SearchService.from_cli_flags(
            professor="홍길동",
            course="감염미생물학",
            year=2024,
            semester=2,
            week_from=1,
            week_to=8,
        )
        assert query.filters is not None
        assert query.filters.professor == "홍길동"
        assert query.filters.course == "감염미생물학"
        assert query.filters.year == 2024
        assert query.filters.semester == 2
        assert query.filters.week_range == [1, 8]

    def test_cli_week_from_only(self) -> None:
        query = SearchService.from_cli_flags(week_from=3)
        assert query.filters is not None
        assert query.filters.week_range == [3, 16]

    def test_cli_week_to_only(self) -> None:
        query = SearchService.from_cli_flags(week_to=8)
        assert query.filters is not None
        assert query.filters.week_range == [1, 8]

    def test_cli_no_flags_returns_empty_query(self) -> None:
        query = SearchService.from_cli_flags()
        assert query.filters is None


class TestSearchServicePerformance:
    """Performance benchmark tests."""

    def test_search_5000_titles_under_5_seconds(self) -> None:
        titles = [
            ParsedTitle(
                video_id=f"vid{i:05d}",
                original_title=(
                    f"교수{i % 50} 20{20 + i % 7} "
                    f"과목{i % 30} {i % 16 + 1}주차 "
                    f"{i % 3 + 1}차시"
                ),
                professor=[f"교수{i % 50}"],
                course=f"과목{i % 30}",
                year=2020 + i % 7,
                semester=(i % 2) + 1,
                week=(i % 16) + 1,
                session=(i % 3) + 1,
                category="regular",
                parse_error=False,
            )
            for i in range(5000)
        ]
        query = SearchQuery(
            queries=[
                SearchFilter(professor="교수5", year=2024),
                SearchFilter(course="과목10", semester=1),
            ],
            exclude=ExcludeRule(title_contains=["2차시"]),
        )
        start = time.time()
        results = SearchService.search(titles, query)
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Search took {elapsed:.2f}s, expected < 5s"
        assert len(results) > 0
