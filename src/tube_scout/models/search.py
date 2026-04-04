"""Search filter and query models."""

from pydantic import BaseModel, Field, field_validator


class SearchFilter(BaseModel):
    """Single filter criteria set with AND logic within.

    Args:
        professor: Professor name for partial match.
        course: Course name for partial match.
        year: Academic year for exact match.
        semester: Semester number (1 or 2) for exact match.
        week_range: Inclusive range [start, end] for week filtering.
        session: Session number for exact match.
    """

    professor: str | None = None
    course: str | None = None
    year: int | None = None
    semester: int | None = None
    week_range: list[int] | None = None
    session: int | None = None

    @field_validator("semester")
    @classmethod
    def semester_must_be_1_or_2(cls, v: int | None) -> int | None:
        """Validate that semester is 1 or 2 if present."""
        if v is not None and v not in (1, 2):
            raise ValueError("semester must be 1 or 2")
        return v

    @field_validator("week_range")
    @classmethod
    def week_range_must_be_valid(cls, v: list[int] | None) -> list[int] | None:
        """Validate that week_range has exactly 2 elements with start <= end."""
        if v is not None:
            if len(v) != 2:
                raise ValueError("week_range must have exactly 2 elements [start, end]")
            if v[0] > v[1]:
                raise ValueError("week_range start must be <= end")
        return v


class ExcludeRule(BaseModel):
    """Exclusion criteria for search.

    Args:
        title_contains: List of keywords to exclude from results.
    """

    title_contains: list[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """Complete search configuration from YAML or CLI.

    Args:
        filters: Single AND filter.
        queries: Multiple OR-combined query groups.
        exclude: Exclusion patterns.
    """

    filters: SearchFilter | None = None
    queries: list[SearchFilter] = Field(default_factory=list)
    exclude: ExcludeRule | None = None
