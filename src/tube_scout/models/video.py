"""Video data model."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Video(BaseModel):
    """YouTube video data model."""

    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    duration_seconds: int = 0
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    has_transcript: bool = False
    transcript_type: str | None = None
    has_analytics: bool = False
    collected_at: datetime | None = None
    description: str | None = None
    tags: list[str] = []
    category_id: str | None = None
    thumbnail_url: str | None = None
    default_language: str | None = None
    privacy_status: str = "public"
    topic_categories: list[str] = []
    has_captions: bool = False

    def title_contains_professor(self, professor_name: str) -> bool:
        """Check if the video title contains the professor name (partial match).

        Args:
            professor_name: Professor name to search for.

        Returns:
            True if professor_name is found in the title.
        """
        return professor_name in self.title


class ViewingPattern(BaseModel):
    """Viewing pattern data for a video segment."""

    video_id: str
    elapsed_ratio: float = Field(..., ge=0.0, le=1.0)
    audience_watch_ratio: float = 0.0
    relative_retention: float = 0.0
    is_rewatch_hotspot: bool = False
    is_skip_zone: bool = False
    collected_at: datetime | None = None


class TranscriptSegment(BaseModel):
    """Transcript-based semantic segment of a video."""

    video_id: str
    segment_index: int
    start_seconds: float
    end_seconds: float
    title: str
    text: str
    summary: str = ""
    difficulty_score: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[str] = []

    @field_validator("end_seconds")
    @classmethod
    def end_must_be_after_start(cls, v: float, info: Any) -> float:
        """Validate that end_seconds > start_seconds."""
        start = info.data.get("start_seconds", 0.0)
        if v <= start:
            raise ValueError("end_seconds must be greater than start_seconds")
        return v


class QualityScore(BaseModel):
    """RACED 5-axis education quality score."""

    video_id: str
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    clarity: float = Field(default=0.0, ge=0.0, le=1.0)
    engagement: float = Field(default=0.0, ge=0.0, le=1.0)
    depth: float = Field(default=0.0, ge=0.0, le=1.0)
    overall: float = 0.0
    evaluated_at: datetime | None = None

    def model_post_init(self, __context: Any) -> None:
        """Compute overall score as weighted average of 5 axes."""
        scores = [
            self.relevance,
            self.accuracy,
            self.clarity,
            self.engagement,
            self.depth,
        ]
        self.overall = sum(scores) / len(scores) if any(s > 0 for s in scores) else 0.0


class Forecast(BaseModel):
    """Time series forecast result."""

    channel_id: str
    metric_name: str
    date: Any  # date object
    predicted_value: float
    lower_bound: float
    upper_bound: float
    is_anomaly: bool = False
    anomaly_reason: str | None = None
