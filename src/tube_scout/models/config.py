"""Configuration and state models for tube-scout."""

import os
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_VALID_DEVICES = {"cpu", "cuda"}

DEFAULT_API_TIMEOUT_SECONDS: int = 60


def get_device() -> str:
    """Read TUBE_SCOUT_DEVICE env var and return validated device string.

    Returns:
        Device string: "cpu" (default) or "cuda".

    Raises:
        ValueError: If env var is set to an invalid value.
    """
    device = os.environ.get("TUBE_SCOUT_DEVICE")
    if device is None:
        return "cpu"
    if device not in _VALID_DEVICES:
        raise ValueError(
            f"TUBE_SCOUT_DEVICE must be one of {sorted(_VALID_DEVICES)}, got {device!r}"
        )
    return device


class RateLimitProfile(BaseModel):
    """Per-service rate limiting configuration."""

    base_delay: float = Field(..., ge=0.0, description="Seconds between requests")
    max_retries: int = Field(..., ge=0, description="Maximum retry attempts on error")
    backoff_multiplier: float = Field(
        ..., ge=1.0, description="Multiplier for exponential backoff"
    )
    jitter: float = Field(
        default=0.5, ge=0.0, description="Random delay variance (± seconds)"
    )


TRANSCRIPT_PROFILE = RateLimitProfile(
    base_delay=2.0,
    max_retries=5,
    backoff_multiplier=3.0,
    jitter=0.5,
)

YOUTUBE_API_PROFILE = RateLimitProfile(
    base_delay=0.1,
    max_retries=3,
    backoff_multiplier=2.0,
    jitter=0.0,
)


class StageResult(BaseModel):
    """Outcome of a single pipeline stage execution."""

    stage_name: str = Field(..., description="Pipeline stage identifier")
    status: Literal["completed", "failed", "skipped"] = Field(
        ..., description="Execution outcome"
    )
    error_message: str | None = None
    items_processed: int = 0
    duration_seconds: float = 0.0


class PipelineResult(BaseModel):
    """Summary of a full collect-all pipeline run."""

    channel_alias: str | None = None
    stages: list[StageResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    resumed: bool = False


class ChannelConfig(BaseModel):
    """Configuration for a single YouTube channel to analyze."""

    channel_id: str = Field(..., min_length=1)
    professor_name: str = Field(..., min_length=1)

    @field_validator("channel_id")
    @classmethod
    def channel_id_must_be_valid(cls, v: str) -> str:
        """Validate channel_id format (UC prefix, alphanum/dash/underscore)."""
        if not re.match(r"^UC[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "channel_id must start with 'UC' and contain "
                "only alphanumeric characters, hyphens, "
                "or underscores"
            )
        return v

    @field_validator("professor_name")
    @classmethod
    def professor_name_must_not_be_blank(cls, v: str) -> str:
        """Validate that professor_name is not blank."""
        if not v.strip():
            raise ValueError("professor_name must not be blank")
        return v.strip()


class Settings(BaseModel):
    """Application settings."""

    data_dir: str = "./data"
    sentiment_backend: str = "llm"
    default_report_format: str = "html"
    llm_provider: str = "claude"
    analytics_start_date: str | None = None
    rate_limit_transcript: RateLimitProfile = Field(
        default_factory=lambda: TRANSCRIPT_PROFILE.model_copy()
    )
    rate_limit_youtube_api: RateLimitProfile = Field(
        default_factory=lambda: YOUTUBE_API_PROFILE.model_copy()
    )


class AppConfig(BaseModel):
    """Top-level application configuration."""

    channels: list[ChannelConfig] = Field(..., min_length=1)
    settings: Settings = Field(default_factory=Settings)

    @field_validator("channels")
    @classmethod
    def channels_must_not_be_empty(cls, v: list[ChannelConfig]) -> list[ChannelConfig]:
        """Validate that at least one channel is configured."""
        if not v:
            raise ValueError("channels must contain at least one entry")
        return v


class CollectionState(BaseModel):
    """Checkpoint state for collection resume support."""

    channel_id: str
    phase: str
    last_page_token: str | None = None
    last_video_id: str | None = None
    total_expected: int = 0
    total_collected: int = 0
    started_at: datetime | None = None
    updated_at: datetime | None = None
    status: str = "in_progress"
    analytics_last_dates: dict[str, str] = {}
    stage_completed: bool = False


VALID_EVENT_TYPES = frozenset({
    "semester_start",
    "semester_end",
    "exam",
    "assignment",
    "holiday",
    "other",
})


class CalendarEvent(BaseModel):
    """A single academic calendar event."""

    name: str = Field(..., min_length=1)
    start_date: str
    end_date: str
    event_type: str

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        """Validate that name is not blank."""
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()

    @field_validator("event_type")
    @classmethod
    def event_type_must_be_valid(cls, v: str) -> str:
        """Validate that event_type is one of the allowed values."""
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(VALID_EVENT_TYPES)}")
        return v

    @field_validator("end_date")
    @classmethod
    def end_date_must_be_gte_start_date(cls, v: str, info: object) -> str:
        """Validate that end_date >= start_date."""
        start = getattr(info, "data", {}).get("start_date")
        if start and v < start:
            raise ValueError("end_date must be >= start_date")
        return v


class AcademicCalendar(BaseModel):
    """Academic calendar with a list of events."""

    events: list[CalendarEvent] = Field(..., min_length=1)

    @field_validator("events")
    @classmethod
    def events_must_not_be_empty(
        cls,
        v: list[CalendarEvent],
    ) -> list[CalendarEvent]:
        """Validate that at least one event is configured."""
        if not v:
            raise ValueError("events must contain at least one entry")
        return v


class ChannelRegistration(BaseModel):
    """A registered department channel for multi-channel management."""

    alias: str = Field(..., min_length=1)
    channel_id: str = Field(..., min_length=1)
    channel_name: str = Field(..., min_length=1)
    registered_at: str
    last_used_at: str
    token_path: str

    @field_validator("alias")
    @classmethod
    def alias_must_not_be_blank(cls, v: str) -> str:
        """Validate that alias is not blank."""
        if not v.strip():
            raise ValueError("alias must not be blank")
        return v

    @field_validator("channel_id")
    @classmethod
    def channel_id_must_start_with_uc(cls, v: str) -> str:
        """Validate that channel_id starts with 'UC'."""
        if not v.startswith("UC"):
            raise ValueError("channel_id must start with 'UC'")
        return v

    @field_validator("channel_name")
    @classmethod
    def channel_name_must_not_be_blank(cls, v: str) -> str:
        """Validate that channel_name is not blank."""
        if not v.strip():
            raise ValueError("channel_name must not be blank")
        return v


class Report(BaseModel):
    """Report metadata model."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    report_type: str
    target_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    format: str = "html"
    file_path: str
