"""Configuration and state models for tube-scout."""

import re
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


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


class Report(BaseModel):
    """Report metadata model."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    report_type: str
    target_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    format: str = "html"
    file_path: str
