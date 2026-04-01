"""YouTube Analytics API service for retention data."""

from typing import Any

from googleapiclient.errors import HttpError


class YouTubeAnalyticsService:
    """Service for interacting with YouTube Analytics API."""

    def __init__(self, client: Any | None = None) -> None:
        """Initialize with an Analytics API client.

        Args:
            client: Pre-built API client (for testing/injection).
        """
        self._client = client

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
                    "elapsed_ratio": row[2],
                    "audience_watch_ratio": row[3],
                    "relative_retention": row[4] if len(row) > 4 else 0.0,
                }
            )
        return result


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
