"""YouTube Data API service for video collection."""

import logging
import re
from typing import Any

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


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

    def __init__(self, client: Any) -> None:
        """Initialize with a pre-built OAuth YouTube API client.

        Args:
            client: Pre-built API client (from auth.build_data_client()).

        Raises:
            TypeError: If client is not provided.
        """
        self._client = client

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
            "subscriber_count": int(
                item["statistics"].get("subscriberCount", 0)
            ),
            "total_view_count": int(item["statistics"].get("viewCount", 0)),
            "description": item["snippet"].get("description"),
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
                    part="snippet,contentDetails,statistics,status,topicDetails",
                    id=",".join(batch),
                )
                .execute()
            )

            for item in response.get("items", []):
                vid_id = item["id"]
                duration = item.get("contentDetails", {}).get("duration", "PT0S")
                stats = item.get("statistics", {})
                snippet = item.get("snippet", {})
                status = item.get("status", {})
                topic_details = item.get("topicDetails", {})
                thumbnails = snippet.get("thumbnails", {})
                default_thumb = thumbnails.get("default", {})
                caption_str = item.get("contentDetails", {}).get("caption", "false")

                results[vid_id] = {
                    "duration_seconds": _parse_iso8601_duration(duration),
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "description": snippet.get("description"),
                    "tags": snippet.get("tags", []),
                    "category_id": snippet.get("categoryId"),
                    "thumbnail_url": default_thumb.get("url"),
                    "default_language": snippet.get("defaultLanguage"),
                    "privacy_status": status.get("privacyStatus", "unknown"),
                    "topic_categories": topic_details.get("topicCategories", []),
                    "has_captions": caption_str == "true",
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
        self,
        video_id: str,
        max_results: int = 100,
        include_replies: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch comments for a video via commentThreads.list with pagination.

        Args:
            video_id: YouTube video ID.
            max_results: Maximum number of top-level comments to fetch.
            include_replies: Whether to also fetch replies for each comment.

        Returns:
            List of comment dicts. Replies have parent_comment_id set.
        """
        comments: list[dict[str, Any]] = []
        token: str | None = None

        try:
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

                response = (
                    self._client.commentThreads().list(**request_params).execute()
                )

                for item in response.get("items", []):
                    thread_snippet = item["snippet"]
                    top_comment = thread_snippet["topLevelComment"]
                    comment_snippet = top_comment["snippet"]
                    reply_count = thread_snippet.get("totalReplyCount", 0)

                    comments.append(
                        {
                            "comment_id": top_comment["id"],
                            "video_id": video_id,
                            "author": comment_snippet.get(
                                "authorDisplayName", ""
                            ),
                            "text": comment_snippet.get("textDisplay", ""),
                            "published_at": comment_snippet.get(
                                "publishedAt", ""
                            ),
                            "like_count": comment_snippet.get("likeCount", 0),
                            "parent_comment_id": None,
                            "reply_count": reply_count,
                        }
                    )

                token = response.get("nextPageToken")
                if not token:
                    break
        except HttpError as e:
            if e.resp.status in (403, 404):
                logger.warning(
                    "Cannot fetch comments for %s: %s", video_id, e
                )
                return []
            raise

        if include_replies:
            threads_with_replies = [
                c for c in comments if c["reply_count"] > 0
            ]
            for thread in threads_with_replies:
                replies = self.get_comment_replies(
                    thread["comment_id"], video_id
                )
                comments.extend(replies)

        return comments

    def get_comment_replies(
        self, parent_id: str, video_id: str
    ) -> list[dict[str, Any]]:
        """Fetch replies for a comment thread.

        Args:
            parent_id: Parent comment ID.
            video_id: Video ID the comment belongs to.

        Returns:
            List of reply comment dicts with parent_comment_id set.
        """
        replies: list[dict[str, Any]] = []
        token: str | None = None

        while True:
            request_params: dict[str, Any] = {
                "part": "snippet",
                "parentId": parent_id,
                "maxResults": 100,
                "textFormat": "plainText",
            }
            if token:
                request_params["pageToken"] = token

            response = self._client.comments().list(**request_params).execute()

            for item in response.get("items", []):
                snippet = item["snippet"]
                replies.append(
                    {
                        "comment_id": item["id"],
                        "video_id": video_id,
                        "author": snippet.get("authorDisplayName", ""),
                        "text": snippet.get("textDisplay", ""),
                        "published_at": snippet.get("publishedAt", ""),
                        "like_count": snippet.get("likeCount", 0),
                        "parent_comment_id": parent_id,
                        "reply_count": 0,
                    }
                )

            token = response.get("nextPageToken")
            if not token:
                break

        return replies

    def detect_new_videos(
        self,
        api_videos: list[dict[str, Any]],
        existing_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Detect videos from the API that are not in the existing set.

        Args:
            api_videos: List of video dicts from the API.
            existing_ids: Set of already-collected video IDs.

        Returns:
            List of new video dicts not in existing_ids.
        """
        return [v for v in api_videos if v["video_id"] not in existing_ids]
