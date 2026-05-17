"""Content reuse detection data models."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from tube_scout.services.takeout_ingest import IngestResult

from tube_scout.models.reuse_v2 import LayerAttribution, ReusePatternLabel


class SuspicionGrade(StrEnum):
    """Priority grade for suspicion score."""

    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    NORMAL = "normal"


VALID_PROCESSING_STATUSES = frozenset({
    "pending",
    "collecting",
    "collected",
    "fingerprinted",
    "compared",
    "failed",
    "no_caption",
    "asr_in_progress",
    "asr_failed",
})

VALID_MATCH_CONFIDENCES = frozenset({"high", "medium", "ambiguous"})

VALID_CAPTION_SOURCES = frozenset({"transcript_api", "captions_api", "whisper"})

VALID_REVIEW_STATUSES = frozenset({
    "UNREVIEWED",
    "PENDING",
    "CONFIRMED_DUPLICATE",
    "FALSE_POSITIVE",
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


# ─── spec 013 v4 models ───────────────────────────────────────────────────────


class AsrQualityFlags(BaseModel):
    """Extensible ASR quality flag set (FR-018).

    Stored as JSON-serialized TEXT in quality_results.asr_quality_flags.
    Ref: data-model.md §E-9.
    """

    hallucination_repeat: bool = False
    vad_over_truncated: bool = False
    language_mismatch: bool = False
    short_segments_excess: bool = False
    silence_hallucination: bool = False
    compression_ratio_violations: int = 0

    model_config = {"extra": "allow"}


class ChannelMetadata(BaseModel):
    """Channel-level metadata ingested from Google Takeout or API.

    Ref: data-model.md §E-1.

    Attributes:
        channel_id: YouTube channel ID (UCxxxx...).
        channel_alias: spec 003 alias resolver key.
        title: Channel display name (required, non-empty).
        country: ISO 3166-1 alpha-2 country code.
        privacy_status: Channel privacy setting.
        source: Data origin.
        takeout_root_hint: Absolute path of most recent Takeout root.
        ingested_at: ISO 8601 timezone-aware ingestion timestamp.
    """

    channel_id: str = Field(..., min_length=1)
    channel_alias: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    country: str | None = Field(None, max_length=2)
    privacy_status: Literal["public", "unlisted", "private"] | None = None
    source: Literal["takeout", "api", "manual"]
    takeout_root_hint: str | None = None
    ingested_at: datetime


class VideoMetadata(BaseModel):
    """Video-level metadata extracted from Takeout CSV or API.

    Ref: data-model.md §E-2.

    Attributes:
        video_id: YouTube video ID (≤ 20 chars).
        channel_id: Parent channel ID.
        title: Video title.
        duration_seconds: Video duration in seconds.
        language: Primary language tag.
        category: YouTube category string.
        privacy_status: Video privacy setting.
        created_at: Video creation timestamp.
        published_at: Video publish timestamp (None for private videos).
        source: Data origin.
        match_confidence: mp4 ↔ video_id mapping confidence.
        mp4_relative_path: Path relative to channel work_dir.
        ingested_at: ISO 8601 timezone-aware ingestion timestamp.
    """

    video_id: str = Field(..., min_length=1, max_length=20)
    channel_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    duration_seconds: float | None = Field(None, ge=0.0)
    language: str | None = None
    category: str | None = None
    privacy_status: Literal["public", "unlisted", "private"] | None = None
    created_at: datetime | None = None
    published_at: datetime | None = None
    source: Literal["takeout", "api"]
    match_confidence: Literal["high", "medium", "ambiguous"] | None = None
    mp4_relative_path: str | None = None
    ingested_at: datetime


# ---------------------------------------------------------------------------
# spec 017 E-5: FailureEntry
# ---------------------------------------------------------------------------


class FailureEntry(BaseModel):
    """Single transcript or fingerprint stage failure for one video.

    Ref: data-model.md §E-5.

    Attributes:
        video_id: YouTube video_id matching SQLite video_metadata.
        title: Video title for operator display.
        failed_stage: Stage that produced the failure.
        failure_reason: Failure cause token (e.g. model_loading_failed).
        attempted_at: UTC timestamp of the attempt.
    """

    video_id: str
    title: str
    failed_stage: Literal["transcript", "fingerprint"]
    failure_reason: str
    attempted_at: datetime


# ---------------------------------------------------------------------------
# spec 017 E-2: TranscriptStageResult
# ---------------------------------------------------------------------------


class TranscriptStageResult(BaseModel):
    """Transcript generation stage summary.

    Ref: data-model.md §E-2.

    Attributes:
        success_count: Videos with transcripts successfully generated.
        failure_count: Videos that failed transcript generation.
        skipped_no_mp4_count: Videos auto-skipped due to absent mp4 (FR-008).
        skip_count: Videos skipped by idempotency guard (spec 018 FR-018F).
        failures: Per-failure details; len must equal failure_count.
        elapsed_seconds: Wall-clock time for this stage.
    """

    success_count: int = Field(..., ge=0)
    failure_count: int = Field(..., ge=0)
    skipped_no_mp4_count: int = Field(..., ge=0)
    skip_count: int = 0
    failures: list[FailureEntry] = Field(default_factory=list)
    elapsed_seconds: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def _failures_length_matches_count(self) -> "TranscriptStageResult":
        if len(self.failures) != self.failure_count:
            raise ValueError(
                f"len(failures)={len(self.failures)} must equal "
                f"failure_count={self.failure_count}"
            )
        return self


# ---------------------------------------------------------------------------
# spec 017 E-3: FingerprintStageResult
# ---------------------------------------------------------------------------


class FingerprintStageResult(BaseModel):
    """Audio fingerprint extraction stage summary.

    Ref: data-model.md §E-3. Structure mirrors TranscriptStageResult.

    Attributes:
        success_count: Videos with fingerprints successfully extracted.
        failure_count: Videos that failed fingerprint extraction.
        skipped_no_mp4_count: Videos auto-skipped due to absent mp4.
        skip_count: Videos skipped by idempotency guard (spec 018 FR-018F).
        failures: Per-failure details; len must equal failure_count.
        elapsed_seconds: Wall-clock time for this stage.
    """

    success_count: int = Field(..., ge=0)
    failure_count: int = Field(..., ge=0)
    skipped_no_mp4_count: int = Field(..., ge=0)
    skip_count: int = 0
    failures: list[FailureEntry] = Field(default_factory=list)
    elapsed_seconds: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def _failures_length_matches_count(self) -> "FingerprintStageResult":
        if len(self.failures) != self.failure_count:
            raise ValueError(
                f"len(failures)={len(self.failures)} must equal "
                f"failure_count={self.failure_count}"
            )
        return self


# ---------------------------------------------------------------------------
# spec 017 E-4: CleanupResult
# ---------------------------------------------------------------------------


class CleanupResult(BaseModel):
    """Source video deletion stage result (--delete-source option).

    Ref: data-model.md §E-4.

    Attributes:
        presented_failure_count: Rows shown in the first prompt failure table.
        deletion_candidate_count: Candidates shown in the second confirmation prompt.
        operator_response: Operator's reply to the deletion confirmation prompt.
        deleted_count: mp4 files actually deleted.
        failed_to_delete_count: mp4 files that failed deletion (file lock, I/O).
        reclaimed_bytes: Disk space reclaimed in bytes.
        elapsed_seconds: Wall-clock time for this stage.
    """

    presented_failure_count: int = Field(..., ge=0)
    deletion_candidate_count: int = Field(..., ge=0)
    operator_response: Literal["yes", "no", "timeout", "interrupted"]
    deleted_count: int = Field(..., ge=0)
    failed_to_delete_count: int = Field(..., ge=0)
    reclaimed_bytes: int = Field(..., ge=0)
    elapsed_seconds: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def _validate_deletion_counts(self) -> "CleanupResult":
        if self.operator_response != "yes":
            if self.deleted_count != 0 or self.failed_to_delete_count != 0:
                raise ValueError(
                    "deleted_count and failed_to_delete_count must be 0 "
                    f"when operator_response={self.operator_response!r}"
                )
        total = self.deleted_count + self.failed_to_delete_count
        if total > self.deletion_candidate_count:
            raise ValueError(
                "deleted_count + failed_to_delete_count must not "
                "exceed deletion_candidate_count"
            )
        return self


# ---------------------------------------------------------------------------
# spec 017 E-6: RetryManifestDelta
# ---------------------------------------------------------------------------


class RetryManifestDelta(BaseModel):
    """Change summary for the retry manifest file after one ingest call.

    Ref: data-model.md §E-6.

    Attributes:
        added_count: Failures newly added to the manifest this call.
        resolved_count: Previously failing videos resolved (now removed).
        remaining_count: Entries remaining in the manifest after this call.
        manifest_path: Absolute path to the manifest file.
    """

    added_count: int = Field(..., ge=0)
    resolved_count: int = Field(..., ge=0)
    remaining_count: int = Field(..., ge=0)
    manifest_path: Path

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# spec 017 E-7: RetryManifestEntry
# ---------------------------------------------------------------------------

VALID_FAILED_STAGES = frozenset({
    "asr",
    "fingerprint",
    "audio_decode",
    "aborted_by_user",
    "ingest_mapping",
    "ingest_no_mp4",
})


class RetryManifestEntry(BaseModel):
    """Single entry in the retry_pending.json manifest (schema_version=2).

    Ref: data-model.md §E-7 Entry (RetryEntry).

    PK = (video_id, mp4_filename, failed_stage) — at least one of video_id
    or mp4_filename must be non-None (validated by model_validator).

    Attributes:
        video_id: YouTube video_id; None for unmapped mp4 (ingest_mapping stage).
        mp4_filename: mp4 basename; None for metadata-only failures.
        title: Video title for operator identification.
        failed_stage: Stage that produced the failure.
        failure_reason: Failure cause token.
        last_attempt_at: UTC timestamp of the last attempt.
        attempt_count: Per-stage independent attempt counter (minimum 1).
    """

    video_id: str | None
    mp4_filename: str | None = None
    title: str
    failed_stage: Literal[
        "asr",
        "fingerprint",
        "audio_decode",
        "aborted_by_user",
        "ingest_mapping",
        "ingest_no_mp4",
    ]
    failure_reason: str
    last_attempt_at: datetime
    attempt_count: int = Field(..., ge=1)

    @model_validator(mode="after")
    def _pk_at_least_one_id(self) -> "RetryManifestEntry":
        if self.video_id is None and self.mp4_filename is None:
            raise ValueError(
                "RetryManifestEntry requires at least one of video_id or "
                "mp4_filename to be non-None."
            )
        return self


# ---------------------------------------------------------------------------
# spec 017 E-1: UnifiedIngestSummary
# ---------------------------------------------------------------------------


class UnifiedIngestSummary(BaseModel):
    """Full result of a single collect ingest command invocation.

    Ref: data-model.md §E-1.

    Wraps IngestResult (spec 016 boundary B-7) together with transcript,
    fingerprint, cleanup, and retry manifest results into one summary.

    Attributes:
        channel_alias: Department alias processed (e.g. nursing).
        ingest_result: spec 016 takeout ingestion result (B-7 preserved).
        transcript_result: Transcript stage result.
        fingerprint_result: Fingerprint stage result.
        cleanup_result: Source video deletion result; None if --delete-source not set.
        retry_manifest_delta: Retry manifest update summary.
        total_elapsed_seconds: Total wall-clock time for the unified command.
        started_at: UTC start timestamp.
        completed_at: UTC end timestamp.
    """

    channel_alias: str
    ingest_result: "IngestResult"
    transcript_result: TranscriptStageResult
    fingerprint_result: FingerprintStageResult
    cleanup_result: CleanupResult | None = None
    retry_manifest_delta: RetryManifestDelta
    total_elapsed_seconds: float = Field(..., ge=0.0)
    started_at: datetime
    completed_at: datetime

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _validate_timing(self) -> "UnifiedIngestSummary":
        if self.started_at >= self.completed_at:
            raise ValueError("started_at must be before completed_at")
        if self.total_elapsed_seconds < self.ingest_result.elapsed_seconds:
            raise ValueError(
                "total_elapsed_seconds must be >= ingest_result.elapsed_seconds"
            )
        return self
