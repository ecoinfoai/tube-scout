"""Tests for YouTubeAnalyticsService."""

from unittest.mock import MagicMock

import pytest

from tube_scout.services.youtube_analytics import (
    YouTubeAnalyticsService,
    detect_rewatch_hotspots,
    detect_skip_zones,
)


@pytest.fixture
def mock_analytics_client() -> MagicMock:
    """Create a mock YouTube Analytics API client."""
    return MagicMock()


@pytest.fixture
def service(mock_analytics_client: MagicMock) -> YouTubeAnalyticsService:
    """Create a YouTubeAnalyticsService with mocked client."""
    return YouTubeAnalyticsService(client=mock_analytics_client)


class TestGetRetentionData:
    """Tests for get_retention_data method (T027)."""

    def test_returns_retention_data(
        self, service: YouTubeAnalyticsService, mock_analytics_client: MagicMock
    ) -> None:
        mock_analytics_client.reports().query().execute.return_value = {
            "rows": [
                [0.0, 1.0, 1.0],
                [0.1, 0.9, 0.95],
                [0.2, 0.85, 0.9],
                [0.3, 0.7, 0.8],
            ],
            "columnHeaders": [
                {"name": "elapsedVideoTimeRatio"},
                {"name": "audienceWatchRatio"},
                {"name": "relativeRetentionPerformance"},
            ],
        }
        result = service.get_retention_data("vid001")
        assert len(result) == 4
        assert result[0]["elapsed_ratio"] == 0.0
        assert result[0]["audience_watch_ratio"] == 1.0

    def test_oauth_error_handled_gracefully(
        self, service: YouTubeAnalyticsService, mock_analytics_client: MagicMock
    ) -> None:
        import httplib2
        from googleapiclient.errors import HttpError

        resp = httplib2.Response({"status": "403"})
        mock_analytics_client.reports().query().execute.side_effect = HttpError(
            resp, b'{"error": {"message": "forbidden"}}'
        )
        with pytest.raises(PermissionError, match="Analytics API"):
            service.get_retention_data("vid001")


class TestRetentionAnalysis:
    """Tests for hotspot/skip detection (T028)."""

    def test_detect_rewatch_hotspots(self) -> None:
        # Synthetic curve: most values around 0.5, one spike at 0.3
        retention = [
            {"elapsed_ratio": i / 10, "audience_watch_ratio": 0.5} for i in range(10)
        ]
        # Create a spike at position 3
        retention[3]["audience_watch_ratio"] = 0.95

        hotspots = detect_rewatch_hotspots(retention)
        assert len(hotspots) >= 1
        hotspot_ratios = [h["elapsed_ratio"] for h in hotspots]
        assert 0.3 in hotspot_ratios

    def test_detect_skip_zones(self) -> None:
        # Synthetic curve: most values around 0.7, one dip at 0.6
        retention = [
            {"elapsed_ratio": i / 10, "audience_watch_ratio": 0.7} for i in range(10)
        ]
        # Create a dip at position 6
        retention[6]["audience_watch_ratio"] = 0.2

        skips = detect_skip_zones(retention)
        assert len(skips) >= 1
        skip_ratios = [s["elapsed_ratio"] for s in skips]
        assert 0.6 in skip_ratios

    def test_no_hotspots_in_flat_curve(self) -> None:
        retention = [
            {"elapsed_ratio": i / 10, "audience_watch_ratio": 0.5} for i in range(10)
        ]
        hotspots = detect_rewatch_hotspots(retention)
        assert len(hotspots) == 0

    def test_no_skip_zones_in_flat_curve(self) -> None:
        retention = [
            {"elapsed_ratio": i / 10, "audience_watch_ratio": 0.5} for i in range(10)
        ]
        skips = detect_skip_zones(retention)
        assert len(skips) == 0
