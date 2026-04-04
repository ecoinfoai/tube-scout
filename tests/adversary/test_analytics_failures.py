"""Adversary tests for analytics collection failure scenarios (T017).

Tests verify graceful handling of: quota exhaustion, API errors,
empty reports, permission errors, and malformed responses.
"""

from datetime import date
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from tube_scout.services.youtube_analytics import YouTubeAnalyticsService


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock YouTube Analytics API client."""
    return MagicMock()


@pytest.fixture
def service(mock_client: MagicMock) -> YouTubeAnalyticsService:
    """Create a YouTubeAnalyticsService with mocked client."""
    return YouTubeAnalyticsService(client=mock_client)


class TestQuotaExhaustion:
    """Tests for API quota exhaustion handling."""

    def test_quota_exceeded_raises_http_error(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        resp = httplib2.Response({"status": "429"})
        mock_client.reports().query().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "quota exceeded"}}'
        )
        with pytest.raises(HttpError):
            service.get_daily_metrics(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_quota_403_raises_permission_error(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        resp = httplib2.Response({"status": "403"})
        mock_client.reports().query().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "forbidden"}}'
        )
        with pytest.raises(PermissionError):
            service.get_daily_metrics(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )


class TestAPIErrors:
    """Tests for various API error responses."""

    def test_401_raises_permission_error(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        resp = httplib2.Response({"status": "401"})
        mock_client.reports().query().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "unauthorized"}}'
        )
        with pytest.raises(PermissionError):
            service.get_traffic_sources(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_500_retried_then_raised(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        resp = httplib2.Response({"status": "500"})
        error = HttpError(resp, b'{"error": {"message": "internal error"}}')
        mock_client.reports().query().execute.side_effect = error

        with pytest.raises(HttpError):
            service.get_geography(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

    def test_no_client_raises_value_error(self) -> None:
        service = YouTubeAnalyticsService(client=None)
        with pytest.raises(ValueError, match="client is not configured"):
            service.get_daily_metrics(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )


class TestEmptyReports:
    """Tests for empty/missing report data."""

    def test_empty_rows_returns_empty_list(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        mock_client.reports().query().execute.return_value = {"rows": []}
        result = service.get_daily_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert result == []

    def test_missing_rows_key_returns_empty_list(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        mock_client.reports().query().execute.return_value = {}
        result = service.get_demographics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert result == []

    def test_all_report_types_handle_empty(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        mock_client.reports().query().execute.return_value = {"rows": []}
        methods = [
            ("get_daily_metrics", {}),
            ("get_traffic_sources", {}),
            ("get_demographics", {}),
            ("get_geography", {}),
            ("get_devices", {}),
            ("get_playback_locations", {}),
            ("get_subscriber_changes", {}),
        ]
        for method_name, extra_kwargs in methods:
            method = getattr(service, method_name)
            result = method(
                channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                **extra_kwargs,
            )
            assert result == [], (
                f"{method_name} should return empty list for empty rows"
            )

    def test_engagement_empty_with_video_filter(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        mock_client.reports().query().execute.return_value = {"rows": []}
        result = service.get_engagement_metrics(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            video_id="dQw4w9WgXcQ",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert result == []


class TestCollectAllReportsFailures:
    """Tests for collect_all_reports with partial failures."""

    def test_partial_failure_collects_successful_reports(
        self, service: YouTubeAnalyticsService, mock_client: MagicMock
    ) -> None:
        resp_500 = httplib2.Response({"status": "500"})
        error = HttpError(resp_500, b'{"error": {"message": "internal"}}')

        call_count = 0

        def execute_side_effect() -> dict:
            nonlocal call_count
            call_count += 1
            # Fail on the second call (after retries exhausted)
            if call_count in (2, 3, 4):  # 3 retries for the 2nd report type
                raise error
            return {"rows": []}

        mock_client.reports().query().execute.side_effect = execute_side_effect

        result = service.collect_all_reports(
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        # Should have collected some reports successfully, errors recorded
        assert "errors" in result
        assert len(result["errors"]) >= 1
