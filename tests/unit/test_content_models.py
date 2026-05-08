"""Tests for content reuse detection Pydantic models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tube_scout.models.content import (
    CaptionFingerprint,
    ComparisonResult,
    ProcessingStatus,
    QualityCheckResult,
    SuspicionGrade,
    SuspicionScore,
)


class TestProcessingStatus:
    """Tests for ProcessingStatus model."""

    def test_create_with_required_fields(self) -> None:
        status = ProcessingStatus(
            video_id="abc123",
            channel_id="UCxyz",
        )
        assert status.video_id == "abc123"
        assert status.channel_id == "UCxyz"
        assert status.status == "pending"
        assert status.caption_source is None
        assert status.error_message is None
        assert status.collected_at is None
        assert status.fingerprinted_at is None

    def test_valid_status_values(self) -> None:
        for s in ("pending", "collecting", "collected", "fingerprinted", "compared", "failed", "no_caption"):
            status = ProcessingStatus(video_id="v1", channel_id="c1", status=s)
            assert status.status == s

    def test_invalid_status_value(self) -> None:
        with pytest.raises(ValidationError):
            ProcessingStatus(video_id="v1", channel_id="c1", status="invalid")

    def test_valid_caption_sources(self) -> None:
        for src in ("transcript_api", "captions_api", "whisper", None):
            status = ProcessingStatus(video_id="v1", channel_id="c1", caption_source=src)
            assert status.caption_source == src

    def test_invalid_caption_source(self) -> None:
        with pytest.raises(ValidationError):
            ProcessingStatus(video_id="v1", channel_id="c1", caption_source="invalid")

    def test_empty_video_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProcessingStatus(video_id="", channel_id="c1")

    def test_serialization_roundtrip(self) -> None:
        now = datetime.now(UTC)
        status = ProcessingStatus(
            video_id="v1",
            channel_id="c1",
            status="collected",
            caption_source="captions_api",
            collected_at=now,
        )
        data = status.model_dump(mode="json")
        restored = ProcessingStatus(**data)
        assert restored.video_id == status.video_id
        assert restored.status == status.status


class TestCaptionFingerprint:
    """Tests for CaptionFingerprint model."""

    def test_create_with_required_fields(self) -> None:
        fp = CaptionFingerprint(
            video_id="v1",
            sha256_hash="a" * 64,
            full_text_length=1000,
        )
        assert fp.video_id == "v1"
        assert fp.sha256_hash == "a" * 64
        assert fp.full_text_length == 1000
        assert fp.embedding_row_index is None

    def test_sha256_hash_must_be_64_chars(self) -> None:
        with pytest.raises(ValidationError):
            CaptionFingerprint(video_id="v1", sha256_hash="short", full_text_length=100)

    def test_full_text_length_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            CaptionFingerprint(video_id="v1", sha256_hash="a" * 64, full_text_length=-1)

    def test_with_embedding_row_index(self) -> None:
        fp = CaptionFingerprint(
            video_id="v1",
            sha256_hash="b" * 64,
            full_text_length=500,
            embedding_row_index=42,
        )
        assert fp.embedding_row_index == 42


class TestComparisonResult:
    """Tests for ComparisonResult model."""

    def test_create_minimal(self) -> None:
        result = ComparisonResult(
            source_video_id="v1",
            target_video_id="v2",
            professor="Kim",
            course="Math101",
            week=1,
            session=1,
            year_from=2025,
            year_to=2026,
        )
        assert result.source_video_id == "v1"
        assert result.review_status == "UNREVIEWED"
        assert result.suspicion_score is None
        assert result.grade is None

    def test_valid_review_statuses(self) -> None:
        for rs in ("UNREVIEWED", "CONFIRMED_DUPLICATE", "FALSE_POSITIVE"):
            result = ComparisonResult(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
                review_status=rs,
            )
            assert result.review_status == rs

    def test_invalid_review_status(self) -> None:
        with pytest.raises(ValidationError):
            ComparisonResult(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
                review_status="INVALID",
            )

    def test_valid_grades(self) -> None:
        for g in ("critical", "high", "moderate", "normal"):
            result = ComparisonResult(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
                grade=g,
            )
            assert result.grade == g

    def test_invalid_grade(self) -> None:
        with pytest.raises(ValidationError):
            ComparisonResult(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
                grade="bad",
            )

    def test_indicator_ranges(self) -> None:
        result = ComparisonResult(
            source_video_id="v1",
            target_video_id="v2",
            professor="Kim",
            course="Math",
            week=1,
            session=1,
            year_from=2025,
            year_to=2026,
            i1_hash_match=True,
            i2_cosine_similarity=0.95,
            i3_change_rate=0.05,
            i4_new_term_count=3,
            i5_duration_diff_seconds=10.5,
            suspicion_score=85.0,
            grade="critical",
        )
        assert result.i1_hash_match is True
        assert result.i2_cosine_similarity == 0.95
        assert result.i3_change_rate == 0.05
        assert result.i4_new_term_count == 3
        assert result.i5_duration_diff_seconds == 10.5
        assert result.suspicion_score == 85.0

    def test_cosine_similarity_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ComparisonResult(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
                i2_cosine_similarity=1.5,
            )

    def test_suspicion_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ComparisonResult(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
                suspicion_score=150.0,
            )


class TestQualityCheckResult:
    """Tests for QualityCheckResult model."""

    def test_create_with_defaults(self) -> None:
        result = QualityCheckResult(video_id="v1")
        assert result.video_id == "v1"
        assert result.q001_voice_present is False
        assert result.q002_min_duration is False
        assert result.q003_course_relevance is None
        assert result.q004_silence_ratio is None
        assert result.q005_speech_density is None
        assert result.pass_count == 0

    def test_pass_count_range(self) -> None:
        result = QualityCheckResult(video_id="v1", pass_count=5)
        assert result.pass_count == 5

    def test_pass_count_exceeds_max(self) -> None:
        with pytest.raises(ValidationError):
            QualityCheckResult(video_id="v1", pass_count=6)

    def test_pass_count_negative(self) -> None:
        with pytest.raises(ValidationError):
            QualityCheckResult(video_id="v1", pass_count=-1)

    def test_all_checks_passed(self) -> None:
        result = QualityCheckResult(
            video_id="v1",
            q001_voice_present=True,
            q002_min_duration=True,
            q003_course_relevance=0.5,
            q004_silence_ratio=0.1,
            q005_speech_density=350.0,
            pass_count=5,
        )
        assert result.pass_count == 5


class TestSuspicionScore:
    """Tests for SuspicionScore model."""

    def test_create(self) -> None:
        score = SuspicionScore(
            score=75.0,
            grade=SuspicionGrade.HIGH,
            i1_contribution=30.0,
            i2_contribution=20.0,
            i3_contribution=15.0,
            i4_contribution=5.0,
            i5_contribution=5.0,
        )
        assert score.score == 75.0
        assert score.grade == SuspicionGrade.HIGH

    def test_score_range(self) -> None:
        with pytest.raises(ValidationError):
            SuspicionScore(
                score=101.0,
                grade=SuspicionGrade.CRITICAL,
                i1_contribution=0,
                i2_contribution=0,
                i3_contribution=0,
                i4_contribution=0,
                i5_contribution=0,
            )

    def test_grade_enum_values(self) -> None:
        assert SuspicionGrade.CRITICAL == "critical"
        assert SuspicionGrade.HIGH == "high"
        assert SuspicionGrade.MODERATE == "moderate"
        assert SuspicionGrade.NORMAL == "normal"
