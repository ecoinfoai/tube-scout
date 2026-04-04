"""Department report data models."""

from pydantic import BaseModel, Field, field_validator

VALID_WEEK_STATUSES = frozenset({"uploaded", "missing", "late"})


class DepartmentOverview(BaseModel):
    """Department-level summary metrics.

    Args:
        channel_id: YouTube channel ID (UC-prefix).
        channel_name: Department/channel display name.
        year: Scoped year if filtered.
        semester: Scoped semester if filtered.
        total_videos: Total video count.
        total_professors: Unique professor count.
        total_courses: Unique course count.
        total_duration_hours: Total duration in hours.
        total_views: Total view count.
        parse_success_rate: Title parse success percentage (0.0-1.0).
    """

    channel_id: str = Field(..., min_length=1)
    channel_name: str = Field(default="")
    year: int | None = None
    semester: int | None = None
    total_videos: int = Field(default=0, ge=0)
    total_professors: int = Field(default=0, ge=0)
    total_courses: int = Field(default=0, ge=0)
    total_duration_hours: float = Field(default=0.0, ge=0.0)
    total_views: int = Field(default=0, ge=0)
    parse_success_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("channel_id")
    @classmethod
    def channel_id_must_start_with_uc(cls, v: str) -> str:
        """Validate that channel_id starts with 'UC'."""
        if not v.startswith("UC"):
            raise ValueError("channel_id must start with 'UC'")
        return v


class ProfessorDetail(BaseModel):
    """Per-professor analysis metrics.

    Args:
        professor_name: Professor name.
        video_count: Number of videos.
        courses: Courses taught.
        weekly_coverage: Percentage of weeks with uploads (1-16).
        session_completeness: Average sessions per week / expected sessions.
        avg_duration_minutes: Average video duration in minutes.
        total_views: Total views across all videos.
        avg_views: Average views per video.
        validation_error_count: Number of validation findings.
    """

    professor_name: str = Field(..., min_length=1)
    video_count: int = Field(default=0, ge=0)
    courses: list[str] = Field(default_factory=list)
    weekly_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    session_completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_duration_minutes: float = Field(default=0.0, ge=0.0)
    total_views: int = Field(default=0, ge=0)
    avg_views: float = Field(default=0.0, ge=0.0)
    validation_error_count: int = Field(default=0, ge=0)

    @field_validator("professor_name")
    @classmethod
    def professor_name_must_not_be_blank(cls, v: str) -> str:
        """Validate that professor_name is not blank."""
        if not v.strip():
            raise ValueError("professor_name must not be blank")
        return v


class ComplianceMatrix(BaseModel):
    """Professor x Week upload status for heatmap.

    Args:
        professor_name: Row identifier.
        week_statuses: Per-week status dict (keys 1-16).
        upload_deadline_compliance: Percentage uploaded before week start.
    """

    professor_name: str = Field(..., min_length=1)
    week_statuses: dict[int, str] = Field(default_factory=dict)
    upload_deadline_compliance: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("professor_name")
    @classmethod
    def professor_name_must_not_be_blank(cls, v: str) -> str:
        """Validate that professor_name is not blank."""
        if not v.strip():
            raise ValueError("professor_name must not be blank")
        return v

    @field_validator("week_statuses")
    @classmethod
    def week_statuses_must_have_valid_values(
        cls, v: dict[int, str],
    ) -> dict[int, str]:
        """Validate that all week status values are valid."""
        for week, status in v.items():
            if status not in VALID_WEEK_STATUSES:
                raise ValueError(
                    f"Invalid status '{status}' for week {week}. "
                    f"Must be one of {sorted(VALID_WEEK_STATUSES)}"
                )
        return v
