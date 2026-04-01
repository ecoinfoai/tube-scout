"""YouTube Data API service for video collection."""

import os
import re
from typing import Any

from googleapiclient.discovery import build


def _parse_iso8601_duration(duration: str) -> int:
    """Parse ISO 8601 duration string to seconds.

    Args:
        duration: ISO 8601 duration (e.g., 'PT1H30M15S').

    Returns:
        Total seconds.
    """
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class YouTubeDataService:
    """Service for interacting with YouTube Data API v3."""

    def __init__(self, client: Any | None = None, api_key: str | None = None) -> None:
        """Initialize with a YouTube API client.

        Args:
            client: Pre-built API client (for testing/injection).
            api_key: YouTube Data API key. Falls back to YOUTUBE_API_KEY env var.
        """
        if client is not None:
            self._client = client
        else:
            key = api_key or os.environ.get("YOUTUBE_API_KEY")
            if not key:
                raise ValueError("YOUTUBE_API_KEY environment variable is required")
            self._client = build("youtube", "v3", developerKey=key)

    def get_channel_info(self, channel_id: str) -> dict[str, Any]:
        """Fetch channel information.

        Args:
            channel_id: YouTube channel ID.

        Returns:
            Dict with channel_id, channel_name, uploads_playlist_id, total_video_count.

        Raises:
            ValueError: If channel is not found.
        """
        response = (
            self._client.channels()
            .list(part="snippet,contentDetails,statistics", id=channel_id)
            .execute()
        )
        items = response.get("items", [])
        if not items:
            raise ValueError(f"Channel not found: {channel_id}")

        item = items[0]
        return {
            "channel_id": item["id"],
            "channel_name": item["snippet"]["title"],
            "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"][
                "uploads"
            ],
            "total_video_count": int(item["statistics"].get("videoCount", 0)),
        }

    def list_all_videos(
        self,
        uploads_playlist_id: str,
        page_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all videos from an uploads playlist with pagination.

        Args:
            uploads_playlist_id: The uploads playlist ID (UU prefix).
            page_token: Token to resume from (for checkpoint support).

        Returns:
            List of video dicts with video_id, title, published_at.
        """
        videos: list[dict[str, Any]] = []
        token = page_token

        while True:
            request_params: dict[str, Any] = {
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if token:
                request_params["pageToken"] = token

            response = self._client.playlistItems().list(**request_params).execute()

            for item in response.get("items", []):
                snippet = item["snippet"]
                videos.append(
                    {
                        "video_id": snippet["resourceId"]["videoId"],
                        "title": snippet["title"],
                        "published_at": snippet["publishedAt"],
                    }
                )

            token = response.get("nextPageToken")
            if not token:
                break

        return videos

    def get_video_details(self, video_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch detailed video information in batches of 50.

        Args:
            video_ids: List of video IDs.

        Returns:
            Dict mapping video_id to details (duration_seconds, view_count, etc.).
        """
        results: dict[str, dict[str, Any]] = {}

        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            response = (
                self._client.videos()
                .list(
                    part="contentDetails,statistics",
                    id=",".join(batch),
                )
                .execute()
            )

            for item in response.get("items", []):
                vid_id = item["id"]
                duration = item["contentDetails"].get("duration", "PT0S")
                stats = item.get("statistics", {})
                results[vid_id] = {
                    "duration_seconds": _parse_iso8601_duration(duration),
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                }

        return results

    def filter_by_professor(
        self, videos: list[dict[str, Any]], professor_name: str
    ) -> list[dict[str, Any]]:
        """Filter videos by professor name in title (partial match).

        Args:
            videos: List of video dicts.
            professor_name: Professor name to filter by.

        Returns:
            Filtered list of videos.
        """
        return [v for v in videos if professor_name in v.get("title", "")]

    def get_comments(
        self, video_id: str, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch comments for a video via commentThreads.list with pagination.

        Args:
            video_id: YouTube video ID.
            max_results: Maximum number of comments to fetch.

        Returns:
            List of comment dicts.
        """
        comments: list[dict[str, Any]] = []
        token: str | None = None

        while len(comments) < max_results:
            page_size = min(100, max_results - len(comments))
            request_params: dict[str, Any] = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": page_size,
                "textFormat": "plainText",
            }
            if token:
                request_params["pageToken"] = token

            response = self._client.commentThreads().list(**request_params).execute()

            for item in response.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append(
                    {
                        "comment_id": item["snippet"]["topLevelComment"]["id"],
                        "video_id": video_id,
                        "author": snippet.get("authorDisplayName", ""),
                        "text": snippet.get("textDisplay", ""),
                        "published_at": snippet.get("publishedAt", ""),
                        "like_count": snippet.get("likeCount", 0),
                    }
                )

            token = response.get("nextPageToken")
            if not token:
                break

        return comments
