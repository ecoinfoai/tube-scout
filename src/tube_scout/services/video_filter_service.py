"""Video filter service for applying filter criteria to video lists."""

import re
from datetime import date

from tube_scout.models.video_filter import VideoFilter

_WEEK_SESSION_RE = re.compile(r"(\d+)\s*주차\s*(\d+)\s*차시")


class VideoFilterService:
    """Service for filtering videos based on VideoFilter criteria."""

    @staticmethod
    def filter_videos(videos: list[dict], video_filter: VideoFilter) -> list[dict]:
        """Filter a list of video metadata dicts by the given criteria.

        All specified conditions are combined with AND logic.

        Args:
            videos: List of video metadata dicts with keys
                'title', 'published_at', 'video_id'.
            video_filter: Filter criteria to apply.

        Returns:
            Filtered list of video dicts matching all conditions.
        """
        result: list[dict] = []
        for video in videos:
            if not VideoFilterService._matches(video, video_filter):
                continue
            result.append(video)
        return result

    @staticmethod
    def _matches(video: dict, video_filter: VideoFilter) -> bool:
        """Check if a single video matches all filter conditions.

        Args:
            video: Video metadata dict.
            video_filter: Filter criteria.

        Returns:
            True if the video matches all specified conditions.
        """
        if video_filter.keyword is not None:
            if video_filter.keyword not in video["title"]:
                return False

        if (
            video_filter.published_after is not None
            or video_filter.published_before is not None
        ):
            pub_date = VideoFilterService._parse_date(video.get("published_at", ""))
            if pub_date is None:
                return False
            if (
                video_filter.published_after is not None
                and pub_date < video_filter.published_after
            ):
                return False
            if (
                video_filter.published_before is not None
                and pub_date > video_filter.published_before
            ):
                return False

        if video_filter.video_ids is not None:
            stripped_ids = [vid.strip() for vid in video_filter.video_ids]
            if video["video_id"] not in stripped_ids:
                return False

        return True

    @staticmethod
    def sort_videos(videos: list[dict], sort_by: str) -> list[dict]:
        """Sort video list by the given criterion.

        Args:
            videos: List of video metadata dicts.
            sort_by: Sort order — 'date', 'course', or 'views'.

        Returns:
            Sorted list of video metadata dicts.
        """
        if sort_by == "views":
            return sorted(
                videos,
                key=lambda v: v.get("view_count", 0),
                reverse=True,
            )
        if sort_by == "course":
            return sorted(
                videos,
                key=VideoFilterService._course_sort_key,
            )
        # Default: date (newest first)
        return sorted(
            videos,
            key=lambda v: v.get("published_at", ""),
            reverse=True,
        )

    @staticmethod
    def _course_sort_key(video: dict) -> tuple[str, int, int]:
        """Generate a sort key for course ordering (subject → week → session).

        Args:
            video: Video metadata dict.

        Returns:
            Tuple of (subject_name, week_number, session_number).
        """
        title = video.get("title", "")
        match = _WEEK_SESSION_RE.search(title)
        week = int(match.group(1)) if match else 9999
        session = int(match.group(2)) if match else 9999
        # Extract subject: take everything before the week/session pattern
        if match:
            subject = title[: match.start()].strip()
        else:
            subject = title
        return (subject, week, session)

    @staticmethod
    def _parse_date(date_str: str) -> date | None:
        """Parse an ISO date string, returning None on failure.

        Args:
            date_str: Date string, typically ISO 8601 format.

        Returns:
            Parsed date object, or None if parsing fails.
        """
        try:
            return date.fromisoformat(date_str[:10])
        except (ValueError, IndexError):
            return None
