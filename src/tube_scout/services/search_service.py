"""Structured search service for parsed video titles."""

from pathlib import Path

import yaml

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.search import ExcludeRule, SearchFilter, SearchQuery


class SearchService:
    """Service for filtering parsed titles using SearchQuery configurations."""

    @staticmethod
    def load_config(yaml_path: Path) -> SearchQuery:
        """Load search configuration from a YAML file.

        Args:
            yaml_path: Path to the YAML search configuration file.

        Returns:
            Validated SearchQuery model.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            ValueError: If the YAML file cannot be parsed or validated.
        """
        if not yaml_path.exists():
            raise FileNotFoundError(f"Search config not found: {yaml_path}")

        raw = yaml_path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML config: {e}") from e

        if not isinstance(data, dict):
            type_name = type(data).__name__
            raise ValueError(
                f"Failed to parse search config: expected a mapping, got {type_name}"
            )

        return _build_query_from_dict(data)

    @staticmethod
    def from_cli_flags(
        professor: str | None = None,
        course: str | None = None,
        year: int | None = None,
        semester: int | None = None,
        week_from: int | None = None,
        week_to: int | None = None,
    ) -> SearchQuery:
        """Convert CLI flags to a SearchQuery.

        Args:
            professor: Professor name for partial match.
            course: Course name for partial match.
            year: Academic year for exact match.
            semester: Semester number (1 or 2).
            week_from: Week range start (inclusive).
            week_to: Week range end (inclusive).

        Returns:
            SearchQuery with a single AND filter, or empty query if no flags.
        """
        has_any = any(
            v is not None
            for v in (professor, course, year, semester, week_from, week_to)
        )
        if not has_any:
            return SearchQuery()

        week_range: list[int] | None = None
        if week_from is not None or week_to is not None:
            start = week_from if week_from is not None else 1
            end = week_to if week_to is not None else 16
            week_range = [start, end]

        return SearchQuery(
            filters=SearchFilter(
                professor=professor,
                course=course,
                year=year,
                semester=semester,
                week_range=week_range,
            ),
        )

    @staticmethod
    def search(
        parsed_titles: list[ParsedTitle],
        query: SearchQuery,
    ) -> list[ParsedTitle]:
        """Search parsed titles using a SearchQuery.

        Args:
            parsed_titles: List of parsed titles to search through.
            query: Search query with filters, queries, and exclude rules.

        Returns:
            Deduplicated list of matching ParsedTitle objects.
        """
        if not parsed_titles:
            return []

        results: list[ParsedTitle] = []
        seen_ids: set[str] = set()

        # Apply single AND filter
        if query.filters is not None:
            for pt in parsed_titles:
                if _matches_filter(pt, query.filters) and pt.video_id not in seen_ids:
                    results.append(pt)
                    seen_ids.add(pt.video_id)

        # Apply OR queries (union)
        if query.queries:
            for pt in parsed_titles:
                if pt.video_id in seen_ids:
                    continue
                if any(_matches_filter(pt, qf) for qf in query.queries):
                    results.append(pt)
                    seen_ids.add(pt.video_id)

        # If no filters and no queries, return all
        if query.filters is None and not query.queries:
            results = list(parsed_titles)

        # Apply exclusions
        if query.exclude and query.exclude.title_contains:
            keywords = query.exclude.title_contains
            results = [
                pt
                for pt in results
                if not any(kw in pt.original_title for kw in keywords)
            ]

        return results


def _matches_filter(pt: ParsedTitle, f: SearchFilter) -> bool:
    """Check if a parsed title matches a single filter (AND logic).

    Args:
        pt: Parsed title to check.
        f: Filter criteria.

    Returns:
        True if all non-None filter fields match.
    """
    if f.professor is not None:
        if not any(f.professor in p for p in pt.professor):
            return False

    if f.course is not None:
        if pt.course is None or f.course not in pt.course:
            return False

    if f.year is not None:
        if pt.year != f.year:
            return False

    if f.semester is not None:
        if pt.semester != f.semester:
            return False

    if f.session is not None:
        if pt.session != f.session:
            return False

    if f.week_range is not None:
        if pt.week is None:
            return False
        if not (f.week_range[0] <= pt.week <= f.week_range[1]):
            return False

    return True


def _build_query_from_dict(data: dict) -> SearchQuery:
    """Build a SearchQuery from a parsed YAML dictionary.

    Args:
        data: Parsed YAML data dictionary.

    Returns:
        Validated SearchQuery.
    """
    filters = None
    if "filters" in data and data["filters"]:
        filters = SearchFilter(**data["filters"])

    queries = []
    if "queries" in data and data["queries"]:
        queries = [SearchFilter(**q) for q in data["queries"]]

    exclude = None
    if "exclude" in data and data["exclude"]:
        exclude = ExcludeRule(**data["exclude"])

    return SearchQuery(filters=filters, queries=queries, exclude=exclude)
