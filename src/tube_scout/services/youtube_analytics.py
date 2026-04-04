"""YouTube Analytics API service for retention and analytics data."""

from __future__ import annotations

import time
from datetime import date
from typing import TYPE_CHECKING, Any

from googleapiclient.errors import HttpError

if TYPE_CHECKING:
    from tube_scout.services.rate_limiter import RateLimiter

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.1  # seconds (kept short for testing; override in production)
_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}


class YouTubeAnalyticsService:
    """Service for interacting with YouTube Analytics API."""

    def __init__(
        self,
        client: Any | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize with an Analytics API client.

        Args:
            client: Pre-built API client (for testing/injection).
            rate_limiter: Optional shared rate limiter for inter-request delays.
        """
        self._client = client
        self._rate_limiter = rate_limiter

    def _ensure_client(self) -> None:
        """Validate that the API client is configured.

        Raises:
            ValueError: If client is not set.
        """
        if self._client is None:
            raise ValueError("Analytics API client is not configured")

    def _query(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        metrics: str,
        dimensions: str = "",
        filters: str = "",
    ) -> list[list[Any]]:
        """Execute an Analytics API query with retry logic.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            metrics: Comma-separated metric names.
            dimensions: Comma-separated dimension names.
            filters: Optional filter expression.

        Returns:
            List of row data from the API response.

        Raises:
            PermissionError: If API access is denied (401/403).
            HttpError: If API returns non-retryable error or retries exhausted.
        """
        self._ensure_client()

        if self._rate_limiter is not None:
            self._rate_limiter.wait()

        query_kwargs: dict[str, str] = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "metrics": metrics,
        }
        if dimensions:
            query_kwargs["dimensions"] = dimensions
        if filters:
            query_kwargs["filters"] = filters

        max_retries = (
            self._rate_limiter.profile.max_retries
            if self._rate_limiter is not None
            else _MAX_RETRIES
        )

        last_error: HttpError | None = None
        for attempt in range(max_retries):
            try:
                response = (
                    self._client.reports()
                    .query(**query_kwargs)
                    .execute()
                )
                return response.get("rows", [])
            except HttpError as e:
                if e.resp.status in (401, 403):
                    raise PermissionError(
                        f"Analytics API access denied for channel {channel_id}. "
                        "Ensure OAuth credentials are configured."
                    ) from e
                if e.resp.status in _RETRYABLE_STATUS_CODES:
                    last_error = e
                    if attempt < max_retries - 1:
                        if self._rate_limiter is not None:
                            self._rate_limiter.wait_on_error(attempt)
                        else:
                            time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                        continue
                raise

        if last_error:
            raise last_error
        return []  # pragma: no cover

    # ----------------------------------------------------------------
    # Retention data (existing functionality)
    # ----------------------------------------------------------------

    def get_retention_data(self, video_id: str) -> list[dict[str, Any]]:
        """Fetch audience retention data for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            List of dicts with elapsed_ratio, audience_watch_ratio,
            relative_retention.

        Raises:
            PermissionError: If Analytics API access is denied.
        """
        if self._client is None:
            raise ValueError("Analytics API client is not configured")

        try:
            response = (
                self._client.reports()
                .query(
                    ids="channel==MINE",
                    startDate="2000-01-01",
                    endDate="2099-12-31",
                    metrics="audienceWatchRatio,relativeRetentionPerformance",
                    dimensions="elapsedVideoTimeRatio",
                    filters=f"video=={video_id}",
                )
                .execute()
            )
        except HttpError as e:
            if e.resp.status in (401, 403):
                raise PermissionError(
                    f"Analytics API access denied for video {video_id}. "
                    "Ensure OAuth credentials are configured."
                ) from e
            raise

        rows = response.get("rows", [])
        result = []
        for row in rows:
            result.append(
                {
                    "elapsed_ratio": row[0],
                    "audience_watch_ratio": row[1],
                    "relative_retention": row[2] if len(row) > 2 else 0.0,
                }
            )
        return result

    # ----------------------------------------------------------------
    # 8 analytics report types (T018-T025)
    # ----------------------------------------------------------------

    def get_daily_metrics(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        video_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch daily time-series metrics.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            video_id: Optional video filter.

        Returns:
            List of daily metric dicts.
        """
        filters = f"video=={video_id}" if video_id else ""
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
            dimensions="day",
            filters=filters,
        )
        return [
            {
                "date": row[0],
                "views": row[1],
                "estimated_minutes_watched": row[2],
                "average_view_duration": row[3],
                "average_view_percentage": row[4],
            }
            for row in rows
        ]

    def get_traffic_sources(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        video_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch traffic source breakdown.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            video_id: Optional video filter.

        Returns:
            List of traffic source dicts.
        """
        filters = f"video=={video_id}" if video_id else ""
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            filters=filters,
        )
        return [
            {
                "source_type": row[0],
                "views": row[1],
                "estimated_minutes_watched": row[2],
            }
            for row in rows
        ]

    def get_demographics(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Fetch viewer demographics (channel-level only).

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.

        Returns:
            List of demographic group dicts.
        """
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="viewerPercentage",
            dimensions="ageGroup,gender",
        )
        return [
            {
                "age_group": row[0],
                "gender": row[1],
                "viewer_percentage": row[2],
            }
            for row in rows
        ]

    def get_geography(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        video_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch geographic viewer distribution.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            video_id: Optional video filter.

        Returns:
            List of geography dicts.
        """
        filters = f"video=={video_id}" if video_id else ""
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            filters=filters,
        )
        return [
            {
                "country": row[0],
                "views": row[1],
                "estimated_minutes_watched": row[2],
            }
            for row in rows
        ]

    def get_devices(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        video_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch device type breakdown.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            video_id: Optional video filter.

        Returns:
            List of device data dicts.
        """
        filters = f"video=={video_id}" if video_id else ""
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="deviceType,operatingSystem",
            filters=filters,
        )
        return [
            {
                "device_type": row[0],
                "operating_system": row[1],
                "views": row[2],
                "estimated_minutes_watched": row[3],
            }
            for row in rows
        ]

    def get_playback_locations(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        video_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch playback location breakdown.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            video_id: Optional video filter.

        Returns:
            List of playback location dicts.
        """
        filters = f"video=={video_id}" if video_id else ""
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightPlaybackLocationType",
            filters=filters,
        )
        return [
            {
                "location_type": row[0],
                "views": row[1],
                "estimated_minutes_watched": row[2],
            }
            for row in rows
        ]

    def get_subscriber_changes(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Fetch daily subscriber gain/loss (channel-level only).

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.

        Returns:
            List of subscriber change dicts.
        """
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="subscribersGained,subscribersLost",
            dimensions="day",
        )
        return [
            {
                "date": row[0],
                "subscribers_gained": row[1],
                "subscribers_lost": row[2],
            }
            for row in rows
        ]

    def get_engagement_metrics(
        self,
        *,
        channel_id: str,
        video_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Fetch per-video engagement metrics.

        Args:
            channel_id: YouTube channel ID.
            video_id: YouTube video ID (required).
            start_date: Query start date.
            end_date: Query end date.

        Returns:
            List of engagement metric dicts.
        """
        rows = self._query(
            channel_id=channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics="shares,likes,comments,averageViewPercentage",
            filters=f"video=={video_id}",
        )
        return [
            {
                "shares": row[0],
                "likes": row[1],
                "comments": row[2],
                "average_view_percentage": row[3],
            }
            for row in rows
        ]

    # ----------------------------------------------------------------
    # Orchestrator (T026)
    # ----------------------------------------------------------------

    def collect_all_reports(
        self,
        *,
        channel_id: str,
        start_date: date,
        end_date: date,
        report_types: list[str] | None = None,
        video_id: str | None = None,
    ) -> dict[str, Any]:
        """Collect multiple analytics report types.

        Args:
            channel_id: YouTube channel ID.
            start_date: Query start date.
            end_date: Query end date.
            report_types: List of report types to collect (None = all).
            video_id: Optional video filter.

        Returns:
            Dict mapping report type to list of result dicts.
            Includes 'errors' key with list of (report_type, error_msg).
        """
        all_types = [
            "daily_metrics",
            "traffic_sources",
            "demographics",
            "geography",
            "devices",
            "playback_locations",
            "subscriber_changes",
        ]

        selected = report_types or all_types
        results: dict[str, Any] = {}
        errors: list[dict[str, str]] = []

        method_map: dict[str, tuple[str, dict[str, Any]]] = {
            "daily_metrics": ("get_daily_metrics", {"video_id": video_id}),
            "traffic_sources": ("get_traffic_sources", {"video_id": video_id}),
            "demographics": ("get_demographics", {}),
            "geography": ("get_geography", {"video_id": video_id}),
            "devices": ("get_devices", {"video_id": video_id}),
            "playback_locations": ("get_playback_locations", {"video_id": video_id}),
            "subscriber_changes": ("get_subscriber_changes", {}),
        }

        for report_type in selected:
            if report_type not in method_map:
                continue
            method_name, extra_kwargs = method_map[report_type]
            # Remove None video_id to avoid passing it to channel-only methods
            kwargs = {k: v for k, v in extra_kwargs.items() if v is not None}
            try:
                method = getattr(self, method_name)
                data = method(
                    channel_id=channel_id,
                    start_date=start_date,
                    end_date=end_date,
                    **kwargs,
                )
                results[report_type] = data
            except Exception as e:
                errors.append({"report_type": report_type, "error": str(e)})

        results["errors"] = errors
        return results


def detect_rewatch_hotspots(
    retention: list[dict[str, Any]],
    threshold_multiplier: float = 1.3,
) -> list[dict[str, Any]]:
    """Detect rewatch hotspots where audience_watch_ratio is above average.

    Args:
        retention: List of retention data points.
        threshold_multiplier: Multiplier above mean to flag as hotspot.

    Returns:
        List of data points identified as rewatch hotspots.
    """
    if not retention:
        return []

    values = [r["audience_watch_ratio"] for r in retention]
    mean_val = sum(values) / len(values)
    threshold = mean_val * threshold_multiplier

    return [r for r in retention if r["audience_watch_ratio"] > threshold]


def detect_skip_zones(
    retention: list[dict[str, Any]],
    threshold_multiplier: float = 0.7,
) -> list[dict[str, Any]]:
    """Detect skip zones where audience_watch_ratio is below average.

    Args:
        retention: List of retention data points.
        threshold_multiplier: Multiplier below mean to flag as skip zone.

    Returns:
        List of data points identified as skip zones.
    """
    if not retention:
        return []

    values = [r["audience_watch_ratio"] for r in retention]
    mean_val = sum(values) / len(values)
    threshold = mean_val * threshold_multiplier

    return [r for r in retention if r["audience_watch_ratio"] < threshold]
