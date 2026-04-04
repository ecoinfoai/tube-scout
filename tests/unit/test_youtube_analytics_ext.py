"""Tests for extended YouTubeAnalyticsService — 8 analytics report type methods."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from tube_scout.services.youtube_analytics import YouTubeAnalyticsService


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock YouTube Analytics API client."""
    return MagicMock()


@pytest.fixture
def service(mock_client: MagicMock) -> YouTubeAnalyticsService:
    """Create a YouTubeAnalyticsService with mocked client."""
    return YouTubeAnalyticsService(client=mock_client)


def _setup_query_response(mock_client: MagicMock, rows: list) -> None:
    """Helper to configure mock client query response."""
    mock_client.reports().query().execute.return_value = {"rows": rows}


class TestGetDailyMetrics:
    """Tests for daily time-series collection (T018)."""

    def test_returns_daily_metrics(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["2024-01-01", 100, 50.5, 120.0, 45.0],
            ["2024-01-02", 200, 100.0, 130.0, 50.0],
        ])
        result = service.get_daily_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["date"] == "2024-01-01"
        assert result[0]["views"] == 100
        assert result[0]["estimated_minutes_watched"] == 50.5
        assert result[0]["average_view_duration"] == 120.0
        assert result[0]["average_view_percentage"] == 45.0

    def test_calls_api_with_correct_params(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_daily_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        mock_client.reports().query.assert_called()
        call_kwargs = mock_client.reports().query.call_args[1]
        assert call_kwargs["dimensions"] == "day"
        assert "views" in call_kwargs["metrics"]
        assert call_kwargs["startDate"] == "2024-01-01"
        assert call_kwargs["endDate"] == "2024-01-31"

    def test_empty_response(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        result = service.get_daily_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert result == []

    def test_with_video_filter(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["2024-01-01", 50, 25.0, 100.0, 40.0],
        ])
        service.get_daily_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            video_id="dQw4w9WgXcQ",
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert "video==dQw4w9WgXcQ" in call_kwargs.get("filters", "")


class TestGetTrafficSources:
    """Tests for traffic source collection (T019)."""

    def test_returns_traffic_sources(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["SUGGESTED", 500, 250.0],
            ["SEARCH", 300, 150.0],
        ])
        result = service.get_traffic_sources(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["source_type"] == "SUGGESTED"
        assert result[0]["views"] == 500

    def test_calls_api_with_correct_dimensions(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_traffic_sources(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert call_kwargs["dimensions"] == "insightTrafficSourceType"


class TestGetDemographics:
    """Tests for demographics collection (T020)."""

    def test_returns_demographics(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["25-34", "male", 35.5],
            ["18-24", "female", 20.0],
        ])
        result = service.get_demographics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["age_group"] == "25-34"
        assert result[0]["gender"] == "male"
        assert result[0]["viewer_percentage"] == 35.5

    def test_calls_api_with_correct_dimensions(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_demographics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert call_kwargs["dimensions"] == "ageGroup,gender"


class TestGetGeography:
    """Tests for geography collection (T021)."""

    def test_returns_geography(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["KR", 10000, 5000.0],
            ["US", 500, 250.0],
        ])
        result = service.get_geography(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["country"] == "KR"
        assert result[0]["views"] == 10000

    def test_calls_api_with_correct_dimensions(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_geography(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert call_kwargs["dimensions"] == "country"


class TestGetDevices:
    """Tests for device/OS collection (T022)."""

    def test_returns_devices(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["MOBILE", "ANDROID", 300, 150.0],
            ["DESKTOP", "WINDOWS", 200, 100.0],
        ])
        result = service.get_devices(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["device_type"] == "MOBILE"
        assert result[0]["operating_system"] == "ANDROID"

    def test_calls_api_with_correct_dimensions(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_devices(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert call_kwargs["dimensions"] == "deviceType,operatingSystem"


class TestGetPlaybackLocations:
    """Tests for playback location collection (T023)."""

    def test_returns_playback_locations(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["WATCH", 1000, 500.0],
            ["EMBEDDED", 200, 100.0],
        ])
        result = service.get_playback_locations(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["location_type"] == "WATCH"
        assert result[0]["views"] == 1000

    def test_calls_api_with_correct_dimensions(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_playback_locations(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert call_kwargs["dimensions"] == "insightPlaybackLocationType"


class TestGetSubscriberChanges:
    """Tests for subscriber change collection (T024)."""

    def test_returns_subscriber_changes(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["2024-01-01", 10, 2],
            ["2024-01-02", 8, 1],
        ])
        result = service.get_subscriber_changes(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 2
        assert result[0]["date"] == "2024-01-01"
        assert result[0]["subscribers_gained"] == 10
        assert result[0]["subscribers_lost"] == 2

    def test_calls_api_with_correct_metrics(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        service.get_subscriber_changes(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        call_kwargs = mock_client.reports().query.call_args[1]
        assert "subscribersGained" in call_kwargs["metrics"]
        assert "subscribersLost" in call_kwargs["metrics"]


class TestGetEngagementMetrics:
    """Tests for engagement metrics collection (T025)."""

    def test_returns_engagement_metrics(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            [5, 50, 10, 45.0],
        ])
        result = service.get_engagement_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            video_id="dQw4w9WgXcQ",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 1
        assert result[0]["shares"] == 5
        assert result[0]["likes"] == 50
        assert result[0]["comments"] == 10
        assert result[0]["average_view_percentage"] == 45.0


class TestCollectAllReports:
    """Tests for the collect_all_reports orchestrator method (T026)."""

    def test_collects_all_report_types(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [])
        result = service.collect_all_reports(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert "daily_metrics" in result
        assert "traffic_sources" in result
        assert "demographics" in result
        assert "geography" in result
        assert "devices" in result
        assert "playback_locations" in result
        assert "subscriber_changes" in result

    def test_collects_single_report_type(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        _setup_query_response(mock_client, [
            ["2024-01-01", 100, 50.5, 120.0, 45.0],
        ])
        result = service.collect_all_reports(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            report_types=["daily_metrics"],
        )
        assert "daily_metrics" in result
        assert "traffic_sources" not in result


class TestRetryLogic:
    """Tests for retry with exponential backoff (T027)."""

    def test_retries_on_transient_error(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        import httplib2
        from googleapiclient.errors import HttpError

        resp_500 = httplib2.Response({"status": "500"})
        error = HttpError(resp_500, b'{"error": {"message": "internal"}}')

        # Fail twice, succeed on third
        mock_client.reports().query().execute.side_effect = [
            error,
            error,
            {"rows": [["2024-01-01", 100, 50.0, 120.0, 45.0]]},
        ]
        result = service.get_daily_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert len(result) == 1

    def test_raises_after_max_retries(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        import httplib2
        from googleapiclient.errors import HttpError

        resp_500 = httplib2.Response({"status": "500"})
        error = HttpError(resp_500, b'{"error": {"message": "internal"}}')
        mock_client.reports().query().execute.side_effect = error

        with pytest.raises(HttpError):
            service.get_daily_metrics(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )
