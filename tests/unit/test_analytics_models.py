"""Tests for analytics data models."""

from datetime import date

import pytest
from pydantic import ValidationError

from tube_scout.models.analytics import (
    AnalyticsReport,
    DailyMetrics,
    DemographicGroup,
    DeviceData,
    GeographyData,
    PlaybackLocation,
    SubscriberChange,
    TrafficSource,
)


class TestAnalyticsReport:
    """Tests for AnalyticsReport model."""

    def test_valid_analytics_report(self) -> None:
        report = AnalyticsReport(
            report_type="daily_metrics",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert report.report_type == "daily_metrics"
        assert report.channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert report.video_id is None
        assert report.rows == []
        assert report.collected_at is not None

    def test_report_type_must_be_valid(self) -> None:
        with pytest.raises(ValidationError, match="report_type"):
            AnalyticsReport(
                report_type="invalid_type",
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_all_valid_report_types(self) -> None:
        valid_types = [
            "daily_metrics",
            "traffic_sources",
            "demographics",
            "geography",
            "devices",
            "playback_locations",
            "subscriber_changes",
            "viewing_patterns",
        ]
        for rt in valid_types:
            report = AnalyticsReport(
                report_type=rt,
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )
            assert report.report_type == rt

    def test_channel_id_must_start_with_uc(self) -> None:
        with pytest.raises(ValidationError, match="channel_id"):
            AnalyticsReport(
                report_type="daily_metrics",
                channel_id="ABinvalid",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_optional_video_id(self) -> None:
        report = AnalyticsReport(
            report_type="daily_metrics",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            video_id="dQw4w9WgXcQ",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert report.video_id == "dQw4w9WgXcQ"

    def test_rows_default_empty(self) -> None:
        report = AnalyticsReport(
            report_type="daily_metrics",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert report.rows == []

    def test_rows_with_data(self) -> None:
        report = AnalyticsReport(
            report_type="daily_metrics",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            rows=[{"date": "2024-01-01", "views": 100}],
        )
        assert len(report.rows) == 1


class TestDailyMetrics:
    """Tests for DailyMetrics model."""

    def test_valid_daily_metrics(self) -> None:
        dm = DailyMetrics(
            date=date(2024, 1, 1),
            views=1000,
            estimated_minutes_watched=500.5,
            average_view_duration=120.0,
            average_view_percentage=45.0,
        )
        assert dm.views == 1000
        assert dm.estimated_minutes_watched == 500.5

    def test_views_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DailyMetrics(
                date=date(2024, 1, 1),
                views=-1,
                estimated_minutes_watched=0.0,
                average_view_duration=0.0,
                average_view_percentage=0.0,
            )

    def test_estimated_minutes_watched_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DailyMetrics(
                date=date(2024, 1, 1),
                views=0,
                estimated_minutes_watched=-1.0,
                average_view_duration=0.0,
                average_view_percentage=0.0,
            )

    def test_average_view_duration_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DailyMetrics(
                date=date(2024, 1, 1),
                views=0,
                estimated_minutes_watched=0.0,
                average_view_duration=-1.0,
                average_view_percentage=0.0,
            )

    def test_average_view_percentage_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            DailyMetrics(
                date=date(2024, 1, 1),
                views=0,
                estimated_minutes_watched=0.0,
                average_view_duration=0.0,
                average_view_percentage=-0.1,
            )

    def test_average_view_percentage_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            DailyMetrics(
                date=date(2024, 1, 1),
                views=0,
                estimated_minutes_watched=0.0,
                average_view_duration=0.0,
                average_view_percentage=100.1,
            )

    def test_average_view_percentage_at_boundaries(self) -> None:
        dm_zero = DailyMetrics(
            date=date(2024, 1, 1),
            views=0,
            estimated_minutes_watched=0.0,
            average_view_duration=0.0,
            average_view_percentage=0.0,
        )
        assert dm_zero.average_view_percentage == 0.0

        dm_hundred = DailyMetrics(
            date=date(2024, 1, 1),
            views=0,
            estimated_minutes_watched=0.0,
            average_view_duration=0.0,
            average_view_percentage=100.0,
        )
        assert dm_hundred.average_view_percentage == 100.0


class TestTrafficSource:
    """Tests for TrafficSource model."""

    def test_valid_traffic_source(self) -> None:
        ts = TrafficSource(
            source_type="SUGGESTED",
            views=500,
            estimated_minutes_watched=250.0,
        )
        assert ts.source_type == "SUGGESTED"
        assert ts.views == 500

    def test_source_type_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="source_type"):
            TrafficSource(
                source_type="",
                views=0,
                estimated_minutes_watched=0.0,
            )

    def test_source_type_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="source_type"):
            TrafficSource(
                source_type="   ",
                views=0,
                estimated_minutes_watched=0.0,
            )

    def test_views_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            TrafficSource(
                source_type="SEARCH",
                views=-1,
                estimated_minutes_watched=0.0,
            )

    def test_estimated_minutes_watched_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            TrafficSource(
                source_type="SEARCH",
                views=0,
                estimated_minutes_watched=-1.0,
            )


class TestDemographicGroup:
    """Tests for DemographicGroup model."""

    def test_valid_demographic_group(self) -> None:
        dg = DemographicGroup(
            age_group="25-34",
            gender="male",
            viewer_percentage=35.5,
        )
        assert dg.age_group == "25-34"
        assert dg.gender == "male"

    def test_age_group_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="age_group"):
            DemographicGroup(
                age_group="",
                gender="male",
                viewer_percentage=10.0,
            )

    def test_gender_must_be_valid(self) -> None:
        with pytest.raises(ValidationError, match="gender"):
            DemographicGroup(
                age_group="25-34",
                gender="unknown",
                viewer_percentage=10.0,
            )

    def test_all_valid_genders(self) -> None:
        for g in ("male", "female", "user_specified"):
            dg = DemographicGroup(
                age_group="18-24",
                gender=g,
                viewer_percentage=33.3,
            )
            assert dg.gender == g

    def test_viewer_percentage_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            DemographicGroup(
                age_group="25-34",
                gender="male",
                viewer_percentage=-0.1,
            )

    def test_viewer_percentage_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            DemographicGroup(
                age_group="25-34",
                gender="male",
                viewer_percentage=100.1,
            )


class TestGeographyData:
    """Tests for GeographyData model."""

    def test_valid_geography_data(self) -> None:
        gd = GeographyData(
            country="KR",
            views=10000,
            estimated_minutes_watched=5000.0,
        )
        assert gd.country == "KR"

    def test_country_must_be_two_letter_alpha(self) -> None:
        with pytest.raises(ValidationError, match="country"):
            GeographyData(
                country="KOR",
                views=100,
                estimated_minutes_watched=50.0,
            )

    def test_country_must_be_uppercase(self) -> None:
        with pytest.raises(ValidationError, match="country"):
            GeographyData(
                country="kr",
                views=100,
                estimated_minutes_watched=50.0,
            )

    def test_country_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="country"):
            GeographyData(
                country="",
                views=100,
                estimated_minutes_watched=50.0,
            )

    def test_views_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            GeographyData(
                country="US",
                views=-1,
                estimated_minutes_watched=0.0,
            )

    def test_estimated_minutes_watched_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            GeographyData(
                country="US",
                views=0,
                estimated_minutes_watched=-1.0,
            )


class TestDeviceData:
    """Tests for DeviceData model."""

    def test_valid_device_data(self) -> None:
        dd = DeviceData(
            device_type="MOBILE",
            operating_system="ANDROID",
            views=300,
            estimated_minutes_watched=150.0,
        )
        assert dd.device_type == "MOBILE"
        assert dd.operating_system == "ANDROID"

    def test_device_type_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="device_type"):
            DeviceData(
                device_type="",
                operating_system="ANDROID",
                views=0,
                estimated_minutes_watched=0.0,
            )

    def test_operating_system_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="operating_system"):
            DeviceData(
                device_type="MOBILE",
                operating_system="",
                views=0,
                estimated_minutes_watched=0.0,
            )

    def test_views_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DeviceData(
                device_type="MOBILE",
                operating_system="ANDROID",
                views=-1,
                estimated_minutes_watched=0.0,
            )

    def test_estimated_minutes_watched_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            DeviceData(
                device_type="MOBILE",
                operating_system="ANDROID",
                views=0,
                estimated_minutes_watched=-1.0,
            )


class TestPlaybackLocation:
    """Tests for PlaybackLocation model."""

    def test_valid_playback_location(self) -> None:
        pl = PlaybackLocation(
            location_type="WATCH",
            views=1000,
            estimated_minutes_watched=500.0,
        )
        assert pl.location_type == "WATCH"

    def test_location_type_must_not_be_blank(self) -> None:
        with pytest.raises(ValidationError, match="location_type"):
            PlaybackLocation(
                location_type="",
                views=0,
                estimated_minutes_watched=0.0,
            )

    def test_views_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PlaybackLocation(
                location_type="EMBEDDED",
                views=-1,
                estimated_minutes_watched=0.0,
            )

    def test_estimated_minutes_watched_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            PlaybackLocation(
                location_type="EMBEDDED",
                views=0,
                estimated_minutes_watched=-1.0,
            )


class TestSubscriberChange:
    """Tests for SubscriberChange model."""

    def test_valid_subscriber_change(self) -> None:
        sc = SubscriberChange(
            date=date(2024, 1, 1),
            subscribers_gained=10,
            subscribers_lost=2,
        )
        assert sc.subscribers_gained == 10
        assert sc.subscribers_lost == 2

    def test_subscribers_gained_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            SubscriberChange(
                date=date(2024, 1, 1),
                subscribers_gained=-1,
                subscribers_lost=0,
            )

    def test_subscribers_lost_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            SubscriberChange(
                date=date(2024, 1, 1),
                subscribers_gained=0,
                subscribers_lost=-1,
            )
