"""Tests for pydantic data models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from tube_scout.models.channel import Channel
from tube_scout.models.comment import Comment
from tube_scout.models.config import (
    AcademicCalendar,
    AppConfig,
    CalendarEvent,
    ChannelConfig,
    CollectionState,
    Report,
    Settings,
)
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


class TestVideoExtendedFields:
    """Tests for Video model extended fields (T006)."""

    def test_new_optional_fields_default(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="Test",
            published_at=datetime(2024, 1, 1),
            duration_seconds=100,
        )
        assert video.description is None
        assert video.tags == []
        assert video.category_id is None
        assert video.thumbnail_url is None
        assert video.default_language is None
        assert video.privacy_status == "public"
        assert video.topic_categories == []
        assert video.has_captions is False

    def test_new_fields_with_values(self) -> None:
        video = Video(
            video_id="dQw4w9WgXcQ",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            title="Test",
            published_at=datetime(2024, 1, 1),
            duration_seconds=100,
            description="A detailed description",
            tags=["lecture", "anatomy"],
            category_id="27",
            thumbnail_url="https://example.com/thumb.jpg",
            default_language="ko",
            privacy_status="unlisted",
            topic_categories=["Science"],
            has_captions=True,
        )
        assert video.description == "A detailed description"
        assert len(video.tags) == 2
        assert video.category_id == "27"
        assert video.has_captions is True


class TestChannelExtendedFields:
    """Tests for Channel model extended fields (T007)."""

    def test_new_fields_default(self) -> None:
        channel = Channel(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            channel_name="Test",
            professor_name="Prof",
        )
        assert channel.subscriber_count == 0
        assert channel.total_view_count == 0
        assert channel.description is None

    def test_new_fields_with_values(self) -> None:
        channel = Channel(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            channel_name="Test",
            professor_name="Prof",
            subscriber_count=5000,
            total_view_count=100000,
            description="A channel about anatomy",
        )
        assert channel.subscriber_count == 5000
        assert channel.total_view_count == 100000
        assert channel.description == "A channel about anatomy"

    def test_subscriber_count_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            Channel(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                channel_name="Test",
                professor_name="Prof",
                subscriber_count=-1,
            )

    def test_total_view_count_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            Channel(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                channel_name="Test",
                professor_name="Prof",
                total_view_count=-1,
            )


class TestCommentExtendedFields:
    """Tests for Comment model extended fields (T008)."""

    def test_new_fields_default(self) -> None:
        comment = Comment(
            comment_id="c1",
            video_id="v1",
            author="A",
            text="text",
            published_at=datetime(2024, 1, 1),
        )
        assert comment.parent_comment_id is None
        assert comment.reply_count == 0

    def test_new_fields_with_values(self) -> None:
        comment = Comment(
            comment_id="c2",
            video_id="v1",
            author="B",
            text="reply text",
            published_at=datetime(2024, 1, 1),
            parent_comment_id="c1",
            reply_count=3,
        )
        assert comment.parent_comment_id == "c1"
        assert comment.reply_count == 3


class TestSettingsExtendedFields:
    """Tests for Settings model extended fields (T005)."""

    def test_new_fields_default(self) -> None:
        settings = Settings()
        assert settings.llm_provider == "claude"
        assert settings.analytics_start_date is None

    def test_new_fields_with_values(self) -> None:
        settings = Settings(
            llm_provider="openai",
            analytics_start_date="2024-01-01",
        )
        assert settings.llm_provider == "openai"
        assert settings.analytics_start_date == "2024-01-01"


class TestCollectionStateExtendedFields:
    """Tests for CollectionState model extended fields (T005)."""

    def test_analytics_last_dates_default(self) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="videos",
        )
        assert state.analytics_last_dates == {}

    def test_analytics_last_dates_with_values(self) -> None:
        state = CollectionState(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            phase="analytics",
            analytics_last_dates={
                "daily_metrics": "2024-03-01",
                "traffic_sources": "2024-03-01",
            },
        )
        assert len(state.analytics_last_dates) == 2
        assert state.analytics_last_dates["daily_metrics"] == "2024-03-01"


class TestCalendarEvent:
    """Tests for CalendarEvent model (T005)."""

    def test_valid_calendar_event(self) -> None:
        event = CalendarEvent(
            name="Mid-term Exam",
            start_date="2024-04-15",
            end_date="2024-04-19",
            event_type="exam",
        )
        assert event.name == "Mid-term Exam"
        assert event.event_type == "exam"

    def test_name_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            CalendarEvent(
                name="",
                start_date="2024-04-15",
                end_date="2024-04-19",
                event_type="exam",
            )

    def test_name_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="name"):
            CalendarEvent(
                name="   ",
                start_date="2024-04-15",
                end_date="2024-04-19",
                event_type="exam",
            )

    def test_event_type_must_be_valid(self) -> None:
        with pytest.raises(ValidationError, match="event_type"):
            CalendarEvent(
                name="Test Event",
                start_date="2024-04-15",
                end_date="2024-04-19",
                event_type="invalid",
            )

    def test_all_valid_event_types(self) -> None:
        valid_types = [
            "semester_start",
            "semester_end",
            "exam",
            "assignment",
            "holiday",
            "other",
        ]
        for et in valid_types:
            event = CalendarEvent(
                name="Test",
                start_date="2024-01-01",
                end_date="2024-01-02",
                event_type=et,
            )
            assert event.event_type == et

    def test_end_date_must_be_gte_start_date(self) -> None:
        with pytest.raises(ValidationError, match="end_date"):
            CalendarEvent(
                name="Bad Event",
                start_date="2024-04-20",
                end_date="2024-04-15",
                event_type="exam",
            )

    def test_same_start_end_date_allowed(self) -> None:
        event = CalendarEvent(
            name="One Day Event",
            start_date="2024-04-15",
            end_date="2024-04-15",
            event_type="holiday",
        )
        assert event.start_date == "2024-04-15"


class TestAcademicCalendar:
    """Tests for AcademicCalendar model (T005)."""

    def test_valid_calendar(self) -> None:
        cal = AcademicCalendar(
            events=[
                CalendarEvent(
                    name="Semester Start",
                    start_date="2024-03-01",
                    end_date="2024-03-01",
                    event_type="semester_start",
                )
            ]
        )
        assert len(cal.events) == 1

    def test_events_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError, match="events"):
            AcademicCalendar(events=[])
