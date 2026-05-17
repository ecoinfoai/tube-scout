"""YouTube Captions API client for private video caption access.

Uses OAuth-authenticated Captions API with youtube.force-ssl scope
to list and download captions from private/unlisted videos.
"""

import logging
from dataclasses import dataclass
from typing import Any

from googleapiclient.errors import HttpError

from tube_scout.services.srt_parser import parse_srt

logger = logging.getLogger(__name__)

# Quota costs per YouTube Data API v3 documentation
QUOTA_COST_LIST = 50
QUOTA_COST_DOWNLOAD = 200

# Language preference order for caption track selection
DEFAULT_LANGUAGE_PREFERENCE = ["ko", "en"]


@dataclass
class CaptionTrack:
    """Represents a caption track from the Captions API.

    Attributes:
        caption_id: YouTube caption track ID.
        language: BCP-47 language code.
        name: Human-readable track name.
        track_kind: Track kind (ASR, standard, forced).
    """

    caption_id: str
    language: str
    name: str
    track_kind: str


class CaptionsAPIClient:
    """Client for YouTube Captions API operations.

    Args:
        youtube_service: Authenticated YouTube Data API v3 service.
        quota_limit: Maximum API quota units to consume (default: 8000).
        language_preference: Ordered list of preferred languages.
    """

    def __init__(
        self,
        youtube_service: Any,
        quota_limit: int = 8000,
        language_preference: list[str] | None = None,
    ) -> None:
        """Initialize with an authenticated YouTube service.

        Args:
            youtube_service: Authenticated YouTube Data API v3 service.
            quota_limit: Maximum API quota units to consume.
            language_preference: Ordered list of preferred languages.
        """
        if youtube_service is None:
            raise ValueError("youtube_service must not be None")
        self._service = youtube_service
        self._quota_limit = quota_limit
        self._quota_used = 0
        self._language_preference = language_preference or DEFAULT_LANGUAGE_PREFERENCE

    @property
    def quota_used(self) -> int:
        """Total API quota units consumed so far."""
        return self._quota_used

    @property
    def quota_remaining(self) -> int:
        """API quota units remaining before limit."""
        return max(0, self._quota_limit - self._quota_used)

    def list_captions(self, video_id: str) -> list[CaptionTrack]:
        """List available caption tracks for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            List of CaptionTrack objects. Empty list on error.
        """
        try:
            response = (
                self._service
                .captions()
                .list(part="snippet", videoId=video_id)
                .execute()
            )
            self._quota_used += QUOTA_COST_LIST
        except HttpError as e:
            logger.warning("Failed to list captions for %s: %s", video_id, e)
            return []

        tracks: list[CaptionTrack] = []
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            tracks.append(
                CaptionTrack(
                    caption_id=item["id"],
                    language=snippet.get("language", ""),
                    name=snippet.get("name", ""),
                    track_kind=snippet.get("trackKind", ""),
                )
            )
        return tracks

    def download_caption(self, caption_id: str) -> str | None:
        """Download caption content in SRT format.

        Args:
            caption_id: YouTube caption track ID.

        Returns:
            SRT content as string, or None on error.
        """
        try:
            content = (
                self._service.captions().download(id=caption_id, tfmt="srt").execute()
            )
            self._quota_used += QUOTA_COST_DOWNLOAD
        except HttpError as e:
            logger.warning("Failed to download caption %s: %s", caption_id, e)
            return None

        if isinstance(content, bytes):
            return content.decode("utf-8")
        return content

    def _select_best_track(self, tracks: list[CaptionTrack]) -> CaptionTrack | None:
        """Select the best caption track based on language preference.

        Args:
            tracks: Available caption tracks.

        Returns:
            Best matching track, or None if no tracks.
        """
        if not tracks:
            return None

        for lang in self._language_preference:
            for track in tracks:
                if track.language == lang:
                    return track

        # Fallback: return first track
        return tracks[0]

    def fetch_segments(self, video_id: str) -> list[dict[str, Any]] | None:
        """List captions, select best track, download, and parse to segments.

        High-level method combining list + download + parse. Respects
        quota limit — returns None if insufficient quota for download.

        Args:
            video_id: YouTube video ID.

        Returns:
            List of segment dicts, or None if no captions or quota exceeded.
        """
        if self.quota_remaining < QUOTA_COST_LIST:
            logger.warning("Insufficient quota to list captions for %s", video_id)
            return None

        tracks = self.list_captions(video_id)
        if not tracks:
            return None

        best_track = self._select_best_track(tracks)
        if best_track is None:
            return None

        if self.quota_remaining < QUOTA_COST_DOWNLOAD:
            logger.warning(
                "Insufficient quota to download caption for %s (need %d, have %d)",
                video_id,
                QUOTA_COST_DOWNLOAD,
                self.quota_remaining,
            )
            return None

        srt_content = self.download_caption(best_track.caption_id)
        if srt_content is None:
            return None

        segments = parse_srt(srt_content)
        return segments if segments else None
