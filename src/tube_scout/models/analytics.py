"""Analytics data models for YouTube Analytics API data."""

import re
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

VALID_REPORT_TYPES = frozenset({
    "daily_metrics",
    "traffic_sources",
    "demographics",
    "geography",
    "devices",
    "playback_locations",
    "subscriber_changes",
    "viewing_patterns",
})


class AnalyticsReport(BaseModel):
    """Container for a YouTube Analytics report."""

    report_type: str
    channel_id: str
    video_id: str | None = None
    start_date: date
    end_date: date
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    rows: list[dict[str, Any]] = []

    @field_validator("report_type")
    @classmethod
    def report_type_must_be_valid(cls, v: str) -> str:
        """Validate that report_type is one of the 8 known types."""
        if v not in VALID_REPORT_TYPES:
            raise ValueError(
                f"report_type must be one of {sorted(VALID_REPORT_TYPES)}"
            )
        return v

    @field_validator("channel_id")
    @classmethod
    def channel_id_must_start_with_uc(cls, v: str) -> str:
        """Validate that channel_id starts with 'UC'."""
        if not re.match(r"^UC[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "channel_id must start with 'UC' and contain "
                "only alphanumeric characters, hyphens, or underscores"
            )
        return v


class DailyMetrics(BaseModel):
    """Daily video/channel performance metrics."""

    date: date
    views: int = Field(..., ge=0)
    estimated_minutes_watched: float = Field(..., ge=0.0)
    average_view_duration: float = Field(..., ge=0.0)
    average_view_percentage: float = Field(..., ge=0.0, le=100.0)


class TrafficSource(BaseModel):
    """Traffic source breakdown data."""

    source_type: str
    views: int = Field(..., ge=0)
    estimated_minutes_watched: float = Field(..., ge=0.0)

    @field_validator("source_type")
    @classmethod
    def source_type_must_not_be_blank(cls, v: str) -> str:
        """Validate that source_type is not blank."""
        if not v.strip():
            raise ValueError("source_type must not be blank")
        return v


class DemographicGroup(BaseModel):
    """Viewer demographic breakdown data."""

    age_group: str
    gender: str
    viewer_percentage: float = Field(..., ge=0.0, le=100.0)

    @field_validator("age_group")
    @classmethod
    def age_group_must_not_be_blank(cls, v: str) -> str:
        """Validate that age_group is not blank."""
        if not v.strip():
            raise ValueError("age_group must not be blank")
        return v

    @field_validator("gender")
    @classmethod
    def gender_must_be_valid(cls, v: str) -> str:
        """Validate that gender is one of the allowed values."""
        allowed = {"male", "female", "user_specified"}
        if v not in allowed:
            raise ValueError(f"gender must be one of {sorted(allowed)}")
        return v


class GeographyData(BaseModel):
    """Geographic viewer distribution data."""

    country: str
    views: int = Field(..., ge=0)
    estimated_minutes_watched: float = Field(..., ge=0.0)

    @field_validator("country")
    @classmethod
    def country_must_be_iso_alpha2(cls, v: str) -> str:
        """Validate that country is ISO 3166-1 alpha-2 (2 uppercase letters)."""
        if not re.match(r"^[A-Z]{2}$", v):
            raise ValueError(
                "country must be ISO 3166-1 alpha-2 (2 uppercase letters)"
            )
        return v


class DeviceData(BaseModel):
    """Device type breakdown data."""

    device_type: str
    operating_system: str
    views: int = Field(..., ge=0)
    estimated_minutes_watched: float = Field(..., ge=0.0)

    @field_validator("device_type")
    @classmethod
    def device_type_must_not_be_blank(cls, v: str) -> str:
        """Validate that device_type is not blank."""
        if not v.strip():
            raise ValueError("device_type must not be blank")
        return v

    @field_validator("operating_system")
    @classmethod
    def operating_system_must_not_be_blank(cls, v: str) -> str:
        """Validate that operating_system is not blank."""
        if not v.strip():
            raise ValueError("operating_system must not be blank")
        return v


class PlaybackLocation(BaseModel):
    """Playback location breakdown data."""

    location_type: str
    views: int = Field(..., ge=0)
    estimated_minutes_watched: float = Field(..., ge=0.0)

    @field_validator("location_type")
    @classmethod
    def location_type_must_not_be_blank(cls, v: str) -> str:
        """Validate that location_type is not blank."""
        if not v.strip():
            raise ValueError("location_type must not be blank")
        return v


class SubscriberChange(BaseModel):
    """Daily subscriber gain/loss data."""

    date: date
    subscribers_gained: int = Field(..., ge=0)
    subscribers_lost: int = Field(..., ge=0)


VALID_JOB_STATUSES = frozenset({"pending", "ready", "downloaded", "failed"})


class ReportingJob(BaseModel):
    """A YouTube Reporting API bulk download job."""

    job_id: str
    report_type_id: str
    channel_id: str = "UCxxxxxxxxxxxxxxxxxxxxxx"
    created_at: str
    status: str = "pending"
    download_url: str | None = None
    downloaded_at: str | None = None

    @field_validator("job_id")
    @classmethod
    def job_id_must_not_be_blank(cls, v: str) -> str:
        """Validate that job_id is not blank."""
        if not v.strip():
            raise ValueError("job_id must not be blank")
        return v

    @field_validator("report_type_id")
    @classmethod
    def report_type_id_must_not_be_blank(cls, v: str) -> str:
        """Validate that report_type_id is not blank."""
        if not v.strip():
            raise ValueError("report_type_id must not be blank")
        return v

    @field_validator("channel_id")
    @classmethod
    def channel_id_must_start_with_uc(cls, v: str) -> str:
        """Validate that channel_id starts with 'UC'."""
        if not re.match(r"^UC[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "channel_id must start with 'UC' and contain "
                "only alphanumeric characters, hyphens, or underscores"
            )
        return v

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        """Validate that status is one of the allowed values."""
        if v not in VALID_JOB_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_JOB_STATUSES)}")
        return v
