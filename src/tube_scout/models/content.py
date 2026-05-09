"""Content reuse detection data models."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from tube_scout.models.reuse_v2 import LayerAttribution, ReusePatternLabel


class SuspicionGrade(StrEnum):
    """Priority grade for suspicion score."""

    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    NORMAL = "normal"


VALID_PROCESSING_STATUSES = frozenset({
    "pending", "collecting", "collected",
    "fingerprinted", "compared", "failed", "no_caption",
})

VALID_CAPTION_SOURCES = frozenset({"transcript_api", "captions_api", "whisper"})

VALID_REVIEW_STATUSES = frozenset({
    "UNREVIEWED", "PENDING", "CONFIRMED_DUPLICATE", "FALSE_POSITIVE",
})

VALID_GRADES = frozenset({"critical", "high", "moderate", "normal"})


class ProcessingStatus(BaseModel):
    """Per-video pipeline progress tracking for resume capability.

    Attributes:
        video_id: YouTube video ID.
        channel_id: Channel the video belongs to.
        status: Current processing state.
        caption_source: How captions were obtained.
        error_message: Last error if status is failed.
        collected_at: When caption was collected.
        fingerprinted_at: When fingerprint was generated.
        updated_at: Last status change.
    """

    video_id: str = Field(..., min_length=1)
    channel_id: str = Field(..., min_length=1)
    status: str = "pending"
    caption_source: str | None = None
    error_message: str | None = None
    collected_at: datetime | None = None
    fingerprinted_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        """Validate that status is a recognized processing state."""
        if v not in VALID_PROCESSING_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(VALID_PROCESSING_STATUSES)}"
            )
        return v

    @field_validator("caption_source")
    @classmethod
    def caption_source_must_be_valid(cls, v: str | None) -> str | None:
        """Validate that caption_source is a recognized source type."""
        if v is not None and v not in VALID_CAPTION_SOURCES:
            raise ValueError(
                f"caption_source must be one of {sorted(VALID_CAPTION_SOURCES)}"
            )
        return v


class CaptionFingerprint(BaseModel):
    """SHA-256 hash and embedding reference for a video's caption text.

    Attributes:
        video_id: YouTube video ID.
        sha256_hash: SHA-256 hex digest of full caption text.
        full_text_length: Character count of full caption text.
        embedding_row_index: Row index in embeddings.parquet.
        created_at: When fingerprint was generated.
    """

    video_id: str = Field(..., min_length=1)
    sha256_hash: str = Field(..., min_length=64, max_length=64)
    full_text_length: int = Field(..., ge=0)
    embedding_row_index: int | None = None
    created_at: datetime | None = None


class ComparisonResult(BaseModel):
    """5-indicator (spec 007) + time-axis (spec 011) analysis for a comparison pair.

    Spec 007 fields are unchanged; spec 011 fields all have defaults so
    existing callers are unaffected (backward-compatible extension).

    Attributes:
        id: Unique comparison ID.
        source_video_id: Video from year A.
        target_video_id: Video from year B.
        professor: Matched professor name.
        course: Matched course name.
        week: Matched week number.
        session: Matched session number.
        year_from: Source video year.
        year_to: Target video year.
        i1_hash_match: I-1: SHA-256 hash identical.
        i2_cosine_similarity: I-2: Embedding cosine similarity (0.0-1.0).
        i3_change_rate: I-3: Text change rate (0.0-1.0, 0=identical).
        i4_new_term_count: I-4: Terms in target not in source.
        i5_duration_diff_seconds: I-5: Duration difference in seconds.
        suspicion_score: Composite score (0-100).
        grade: Priority grade.
        review_status: Administrator review status.
        reviewed_at: When review status was set.
        reviewed_by: Reviewer identifier.
        created_at: When comparison was performed.
        matching_mode: Analysis mode — M-default (spec 007) or M-nC2 (spec 011).
        professor_id: Professor pool identifier (spec 011 nC2 runs only).
        i6_longest_contiguous_seconds: I-6: Longest contiguous matching span (seconds).
        i7_distribution_dispersion: I-7: Dispersion of matching span lengths.
        i8_position_diversity: I-8: Spread of spans across timeline thirds (0-1).
        reuse_pattern: 4-way pattern classification (spec 011 only).
        layer_attribution: Defense-layer audit trail for this pair.
        baseline_subtracted_length_seconds: Seconds removed by Layer B baseline.
        pre_subtraction_i2: I-2 value before Layer B subtraction (audit).
        pre_subtraction_i6: I-6 value before Layer B subtraction (audit).
    """

    id: int | None = None
    source_video_id: str = Field(..., min_length=1)
    target_video_id: str = Field(..., min_length=1)
    professor: str
    course: str
    week: int
    session: int
    year_from: int
    year_to: int
    i1_hash_match: bool | None = None
    i2_cosine_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    i3_change_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    i4_new_term_count: int | None = None
    i5_duration_diff_seconds: float | None = None
    suspicion_score: float | None = Field(default=None, ge=0.0, le=100.0)
    grade: str | None = None
    review_status: str = "UNREVIEWED"
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    created_at: datetime | None = None
    # spec 011 extension fields — all optional, default-safe for spec 007 callers
    matching_mode: Literal["M-default", "M-nC2"] = "M-default"
    professor_id: str | None = None
    i6_longest_contiguous_seconds: float | None = None
    i7_distribution_dispersion: float | None = None
    i8_position_diversity: float | None = None
    reuse_pattern: ReusePatternLabel | None = None
    layer_attribution: list[LayerAttribution] = Field(default_factory=list)
    baseline_subtracted_length_seconds: float | None = None
    pre_subtraction_i2: float | None = None
    pre_subtraction_i6: float | None = None

    @field_validator("grade")
    @classmethod
    def grade_must_be_valid(cls, v: str | None) -> str | None:
        """Validate that grade is a recognized priority level."""
        if v is not None and v not in VALID_GRADES:
            raise ValueError(f"grade must be one of {sorted(VALID_GRADES)}")
        return v

    @field_validator("review_status")
    @classmethod
    def review_status_must_be_valid(cls, v: str) -> str:
        """Validate that review_status is a recognized status."""
        if v not in VALID_REVIEW_STATUSES:
            raise ValueError(
                f"review_status must be one of {sorted(VALID_REVIEW_STATUSES)}"
            )
        return v


class QualityCheckResult(BaseModel):
    """Per-video quality rule pass/fail results.

    Attributes:
        video_id: YouTube video ID.
        q001_voice_present: Has extractable captions.
        q002_min_duration: Duration >= 5 minutes.
        q003_course_relevance: Proportion of course-related terms.
        q004_silence_ratio: Ratio of inter-segment gaps.
        q005_speech_density: Characters per minute.
        pass_count: Number of rules passed (0-5).
        checked_at: When quality check was performed.
    """

    video_id: str = Field(..., min_length=1)
    q001_voice_present: bool = False
    q002_min_duration: bool = False
    q003_course_relevance: float | None = None
    q004_silence_ratio: float | None = None
    q005_speech_density: float | None = None
    pass_count: int = Field(default=0, ge=0, le=5)
    checked_at: datetime | None = None


class SuspicionScore(BaseModel):
    """Composite suspicion score with per-indicator contributions.

    Attributes:
        score: Composite score (0-100).
        grade: Priority grade.
        i1_contribution: I-1 hash match contribution.
        i2_contribution: I-2 cosine similarity contribution.
        i3_contribution: I-3 text change rate contribution.
        i4_contribution: I-4 new term count contribution.
        i5_contribution: I-5 duration difference contribution.
    """

    score: float = Field(..., ge=0.0, le=100.0)
    grade: SuspicionGrade
    i1_contribution: float
    i2_contribution: float
    i3_contribution: float
    i4_contribution: float
    i5_contribution: float
