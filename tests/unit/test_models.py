"""Tests for pydantic data models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from tube_scout.models.channel import Channel
from tube_scout.models.comment import Comment
from tube_scout.models.config import AppConfig, ChannelConfig, Report, Settings
from tube_scout.models.video import (
    Forecast,
    QualityScore,
    TranscriptSegment,
    Video,
    ViewingPattern,
)


class TestChannelConfig:
    """Tests for ChannelConfig model."""

    def test_valid_channel_config(self) -> None:
        config = ChannelConfig(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            professor_name="TestProfessor",
        )
        assert config.channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert config.professor_name == "TestProfessor"

    def test_channel_id_must_start_with_uc(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(
                channel_id="ABxxxxxxxxxxxxxxxxxxxxxx",
                professor_name="TestProfessor",
            )

    def test_channel_id_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChannelConfig(channel_id="", professor_name="TestProfessor")

    def test_professor_name_non_empty(self) -> None:
        with pytest.raises(ValidationError, match="professor_name"):
            ChannelConfig(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                professor_name="",
            )

    def test_professor_name_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="professor_name"):
            ChannelConfig(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                professor_name="   ",
            )

    def test_channel_id_with_spaces_rejected(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(
                channel_id="UC xxxx with spaces",
                professor_name="TestProfessor",
            )

    def test_channel_id_with_special_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            ChannelConfig(
                channel_id="UC@#$%^&*()",
                professor_name="TestProfessor",
            )

    def test_channel_id_with_hyphens_and_underscores_ok(self) -> None:
        config = ChannelConfig(
            channel_id="UC_test-channel_123",
            professor_name="TestProfessor",
        )
        assert config.channel_id == "UC_test-channel_123"


class TestSettings:
    """Tests for Settings model."""

    def test_default_settings(self) -> None:
        settings = Settings()
        assert settings.data_dir == "./data"
        assert settings.sentiment_backend == "llm"
        assert settings.default_report_format == "html"

    def test_custom_settings(self) -> None:
        settings = Settings(
            data_dir="/custom/path",
            sentiment_backend="local",
            default_report_format="notebook",
        )
        assert settings.data_dir == "/custom/path"
        assert settings.sentiment_backend == "local"


class TestAppConfig:
    """Tests for AppConfig model."""

    def test_valid_app_config(self) -> None:
        config = AppConfig(
            channels=[
                ChannelConfig(
                    channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                    professor_name="TestProfessor",
                )
            ],
            settings=Settings(),
        )
        assert len(config.channels) == 1

    def test_channels_is_list(self) -> None:
        config = AppConfig(
            channels=[
                ChannelConfig(
                    channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                    professor_name="Prof1",
                ),
                ChannelConfig(
                    channel_id="UCyyyyyyyyyyyyyyyyyyyyyy",
                    professor_name="Prof2",
                ),
            ],
            settings=Settings(),
        )
        assert len(config.channels) == 2

    def test_empty_channels_rejected(self) -> None:
        with pytest.raises(ValidationError, match="channels"):
            AppConfig(channels=[], settings=Settings())

    def test_default_settings_applied(self) -> None:
        config = AppConfig(
            channels=[
                ChannelConfig(
                    channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                    professor_name="TestProfessor",
                )
            ],
        )
        assert config.settings.data_dir == "./data"


class TestChannel:
    """Tests for Channel model (T017)."""

    def test_uploads_playlist_id_derived_from_channel_id(self) -> None:
        channel = Channel(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            channel_name="Test Channel",
            professor_name="Prof",
        )
        assert channel.uploads_playlist_id == "UUxxxxxxxxxxxxxxxxxxxxxx"

    def test_channel_id_validation(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            Channel(
                channel_id="ABinvalid",
                channel_name="Test",
                professor_name="Prof",
            )

    def test_default_counts(self) -> None:
        channel = Channel(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            channel_name="Test",
            professor_name="Prof",
        )
        assert channel.total_video_count == 0
        assert channel.filtered_video_count == 0
        assert channel.last_collected_at is None


class TestVideo:
    """Tests for Video model (T018)."""

    def test_valid_video(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="Test Professor Lecture 1",
            published_at=datetime(2024, 1, 1),
            duration_seconds=600,
            view_count=1000,
            like_count=50,
            comment_count=10,
        )
        assert video.video_id == "dQw4w9WgXcQ"
        assert video.duration_seconds == 600

    def test_title_contains_professor_exact(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="홍길동 교수의 해부학 강의",
            published_at=datetime(2024, 1, 1),
            duration_seconds=600,
        )
        assert video.title_contains_professor("홍길동") is True

    def test_title_contains_professor_partial(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="해부학 홍길동교수 특강",
            published_at=datetime(2024, 1, 1),
            duration_seconds=600,
        )
        assert video.title_contains_professor("홍길동") is True

    def test_title_not_contains_professor(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="다른 교수의 강의",
            published_at=datetime(2024, 1, 1),
            duration_seconds=600,
        )
        assert video.title_contains_professor("홍길동") is False

    def test_default_optional_fields(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="Test",
            published_at=datetime(2024, 1, 1),
            duration_seconds=100,
        )
        assert video.view_count == 0
        assert video.like_count == 0
        assert video.comment_count == 0
        assert video.has_transcript is False
        assert video.transcript_type is None
        assert video.has_analytics is False


class TestViewingPattern:
    """Tests for ViewingPattern model (T026)."""

    def test_valid_viewing_pattern(self) -> None:
        vp = ViewingPattern(
            video_id="vid001",
            elapsed_ratio=0.5,
            audience_watch_ratio=0.8,
            relative_retention=1.2,
        )
        assert vp.elapsed_ratio == 0.5
        assert vp.audience_watch_ratio == 0.8
        assert vp.is_rewatch_hotspot is False
        assert vp.is_skip_zone is False

    def test_elapsed_ratio_range_lower(self) -> None:
        with pytest.raises(ValidationError):
            ViewingPattern(
                video_id="vid001",
                elapsed_ratio=-0.1,
                audience_watch_ratio=0.5,
            )

    def test_elapsed_ratio_range_upper(self) -> None:
        with pytest.raises(ValidationError):
            ViewingPattern(
                video_id="vid001",
                elapsed_ratio=1.1,
                audience_watch_ratio=0.5,
            )

    def test_hotspot_flag(self) -> None:
        vp = ViewingPattern(
            video_id="vid001",
            elapsed_ratio=0.3,
            audience_watch_ratio=0.9,
            is_rewatch_hotspot=True,
        )
        assert vp.is_rewatch_hotspot is True

    def test_skip_zone_flag(self) -> None:
        vp = ViewingPattern(
            video_id="vid001",
            elapsed_ratio=0.7,
            audience_watch_ratio=0.2,
            is_skip_zone=True,
        )
        assert vp.is_skip_zone is True


class TestComment:
    """Tests for Comment model (T035)."""

    def test_valid_comment(self) -> None:
        comment = Comment(
            comment_id="comment001",
            video_id="vid001",
            author="Student",
            text="Great lecture!",
            published_at=datetime(2024, 3, 1),
        )
        assert comment.comment_id == "comment001"
        assert comment.sentiment is None
        assert comment.topics == []
        assert comment.is_question is False

    def test_sentiment_values(self) -> None:
        for sentiment in ("positive", "negative", "neutral"):
            comment = Comment(
                comment_id="c1",
                video_id="v1",
                author="A",
                text="text",
                published_at=datetime(2024, 1, 1),
                sentiment=sentiment,
            )
            assert comment.sentiment == sentiment

    def test_topics_list(self) -> None:
        comment = Comment(
            comment_id="c1",
            video_id="v1",
            author="A",
            text="Can you explain the cell membrane structure?",
            published_at=datetime(2024, 1, 1),
            topics=["cell biology", "membrane"],
            is_question=True,
        )
        assert len(comment.topics) == 2
        assert comment.is_question is True

    def test_analysis_backend_field(self) -> None:
        comment = Comment(
            comment_id="c1",
            video_id="v1",
            author="A",
            text="text",
            published_at=datetime(2024, 1, 1),
            analysis_backend="llm",
            analyzed_at=datetime(2024, 3, 15),
        )
        assert comment.analysis_backend == "llm"
        assert comment.analyzed_at is not None


class TestTranscriptSegment:
    """Tests for TranscriptSegment model (T043)."""

    def test_valid_segment(self) -> None:
        seg = TranscriptSegment(
            video_id="vid001",
            segment_index=0,
            start_seconds=0.0,
            end_seconds=120.5,
            title="Introduction",
            text="Welcome to today's lecture...",
            summary="Introduction to cell biology.",
            difficulty_score=0.3,
            tags=["introduction", "cell biology"],
        )
        assert seg.segment_index == 0
        assert seg.start_seconds < seg.end_seconds

    def test_time_range_validation(self) -> None:
        with pytest.raises(ValidationError, match="end_seconds"):
            TranscriptSegment(
                video_id="vid001",
                segment_index=0,
                start_seconds=100.0,
                end_seconds=50.0,
                title="Bad segment",
                text="text",
            )

    def test_difficulty_score_range_low(self) -> None:
        with pytest.raises(ValidationError):
            TranscriptSegment(
                video_id="vid001",
                segment_index=0,
                start_seconds=0.0,
                end_seconds=60.0,
                title="Test",
                text="text",
                difficulty_score=-0.1,
            )

    def test_difficulty_score_range_high(self) -> None:
        with pytest.raises(ValidationError):
            TranscriptSegment(
                video_id="vid001",
                segment_index=0,
                start_seconds=0.0,
                end_seconds=60.0,
                title="Test",
                text="text",
                difficulty_score=1.1,
            )

    def test_default_difficulty(self) -> None:
        seg = TranscriptSegment(
            video_id="vid001",
            segment_index=0,
            start_seconds=0.0,
            end_seconds=60.0,
            title="Test",
            text="text",
        )
        assert seg.difficulty_score == 0.0
        assert seg.tags == []


class TestReport:
    """Tests for Report model (T052)."""

    def test_valid_report(self) -> None:
        report = Report(
            report_type="video",
            target_id="vid001",
            format="html",
            file_path="data/reports/video/vid001.html",
        )
        assert report.report_id is not None
        assert report.report_type == "video"
        assert report.generated_at is not None

    def test_report_type_enum(self) -> None:
        for rtype in ("video", "channel", "comment_insight"):
            report = Report(
                report_type=rtype,
                target_id="target1",
                format="html",
                file_path="path.html",
            )
            assert report.report_type == rtype

    def test_file_path_generation(self) -> None:
        report = Report(
            report_type="video",
            target_id="vid001",
            format="html",
            file_path="data/reports/video/vid001.html",
        )
        assert "vid001" in report.file_path


class TestQualityScore:
    """Tests for QualityScore model (T060)."""

    def test_valid_scores(self) -> None:
        qs = QualityScore(
            video_id="vid001",
            relevance=0.8,
            accuracy=0.9,
            clarity=0.7,
            engagement=0.6,
            depth=0.85,
        )
        assert qs.relevance == 0.8
        assert 0.0 <= qs.overall <= 1.0

    def test_overall_is_weighted_average(self) -> None:
        qs = QualityScore(
            video_id="vid001",
            relevance=0.8,
            accuracy=0.8,
            clarity=0.8,
            engagement=0.8,
            depth=0.8,
        )
        assert abs(qs.overall - 0.8) < 0.01

    def test_score_range_validation_low(self) -> None:
        with pytest.raises(ValidationError):
            QualityScore(
                video_id="vid001",
                relevance=-0.1,
                accuracy=0.5,
                clarity=0.5,
                engagement=0.5,
                depth=0.5,
            )

    def test_score_range_validation_high(self) -> None:
        with pytest.raises(ValidationError):
            QualityScore(
                video_id="vid001",
                relevance=1.1,
                accuracy=0.5,
                clarity=0.5,
                engagement=0.5,
                depth=0.5,
            )


class TestForecast:
    """Tests for Forecast model (T066)."""

    def test_valid_forecast(self) -> None:
        from datetime import date

        fc = Forecast(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="view_count",
            date=date(2024, 6, 1),
            predicted_value=1500.0,
            lower_bound=1200.0,
            upper_bound=1800.0,
        )
        assert fc.predicted_value == 1500.0
        assert fc.is_anomaly is False

    def test_confidence_interval(self) -> None:
        from datetime import date

        fc = Forecast(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="view_count",
            date=date(2024, 6, 1),
            predicted_value=1500.0,
            lower_bound=1200.0,
            upper_bound=1800.0,
        )
        assert fc.lower_bound <= fc.predicted_value <= fc.upper_bound

    def test_anomaly_flag(self) -> None:
        from datetime import date

        fc = Forecast(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            metric_name="view_count",
            date=date(2024, 3, 15),
            predicted_value=5000.0,
            lower_bound=1200.0,
            upper_bound=1800.0,
            is_anomaly=True,
            anomaly_reason="Mid-term exam period",
        )
        assert fc.is_anomaly is True
        assert fc.anomaly_reason is not None
