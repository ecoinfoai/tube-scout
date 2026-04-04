"""Parsed video title model."""

from pydantic import BaseModel, Field, field_validator

VALID_CATEGORIES = frozenset({"regular", "supplementary"})


class ParsedTitle(BaseModel):
    """Structured data extracted from a video title.

    Args:
        video_id: YouTube video ID.
        original_title: Unmodified original title.
        professor: List of professor names extracted from the title.
        course: Course/subject name if detected.
        year: Academic year (2000-2099) if detected.
        semester: Semester number (1 or 2) if detected.
        week: Week number if detected.
        session: Session/class number if detected.
        department: Department name if present in title.
        category: "regular" or "supplementary".
        parse_error: True if title could not be fully parsed.
        matched_pattern: Name of the regex pattern that matched.
    """

    video_id: str = Field(..., min_length=1)
    original_title: str = Field(..., min_length=1)
    professor: list[str] = Field(default_factory=list)
    course: str | None = None
    year: int | None = None
    semester: int | None = None
    week: int | None = None
    session: int | None = None
    department: str | None = None
    category: str = "regular"
    parse_error: bool = False
    matched_pattern: str | None = None

    @field_validator("original_title")
    @classmethod
    def original_title_must_not_be_blank(cls, v: str) -> str:
        """Validate that original_title is not blank."""
        if not v.strip():
            raise ValueError("original_title must not be blank")
        return v

    @field_validator("year")
    @classmethod
    def year_must_be_in_range(cls, v: int | None) -> int | None:
        """Validate that year is between 2000 and 2099 if present."""
        if v is not None and (v < 2000 or v > 2099):
            raise ValueError("year must be between 2000 and 2099")
        return v

    @field_validator("semester")
    @classmethod
    def semester_must_be_1_or_2(cls, v: int | None) -> int | None:
        """Validate that semester is 1 or 2 if present."""
        if v is not None and v not in (1, 2):
            raise ValueError("semester must be 1 or 2")
        return v

    @field_validator("category")
    @classmethod
    def category_must_be_valid(cls, v: str) -> str:
        """Validate that category is 'regular' or 'supplementary'."""
        if v not in VALID_CATEGORIES:
            raise ValueError(
                f"category must be one of {sorted(VALID_CATEGORIES)}"
            )
        return v
