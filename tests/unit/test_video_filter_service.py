"""Unit tests for VideoFilterService."""

import pytest

from tube_scout.models.video_filter import VideoFilter
from tube_scout.services.video_filter_service import VideoFilterService


@pytest.fixture()
def sample_videos() -> list[dict]:
    """Create a sample list of video metadata dicts."""
    return [
        {
            "video_id": "vid001",
            "title": "감염미생물학 1주차 강의",
            "published_at": "2026-01-15T10:00:00Z",
        },
        {
            "video_id": "vid002",
            "title": "인체구조와기능 2주차 강의",
            "published_at": "2026-02-10T10:00:00Z",
        },
        {
            "video_id": "vid003",
            "title": "감염미생물학 3주차 강의",
            "published_at": "2026-03-05T10:00:00Z",
        },
        {
            "video_id": "vid004",
            "title": "기초간호학 4주차 강의",
            "published_at": "2026-04-20T10:00:00Z",
        },
        {
            "video_id": "vid005",
            "title": "감염미생물학 특강",
            "published_at": "2025-12-01T10:00:00Z",
        },
    ]


class TestVideoFilterService:
    """Tests for VideoFilterService.filter_videos."""

    def test_filter_by_keyword(self, sample_videos: list[dict]) -> None:
        """Keyword filter returns only matching titles."""
        vf = VideoFilter(keyword="감염미생물학")
        result = VideoFilterService.filter_videos(sample_videos, vf)
        assert len(result) == 3
        assert all("감염미생물학" in v["title"] for v in result)

    def test_filter_by_date_range(self, sample_videos: list[dict]) -> None:
        """Date range filter returns only videos within range."""
        from datetime import date

        vf = VideoFilter(
            published_after=date(2026, 1, 1),
            published_before=date(2026, 3, 31),
        )
        result = VideoFilterService.filter_videos(sample_videos, vf)
        assert len(result) == 3
        video_ids = {v["video_id"] for v in result}
        assert video_ids == {"vid001", "vid002", "vid003"}

    def test_filter_combined(self, sample_videos: list[dict]) -> None:
        """Keyword + date range AND combination."""
        from datetime import date

        vf = VideoFilter(
            keyword="감염미생물학",
            published_after=date(2026, 1, 1),
            published_before=date(2026, 3, 31),
        )
        result = VideoFilterService.filter_videos(sample_videos, vf)
        assert len(result) == 2
        video_ids = {v["video_id"] for v in result}
        assert video_ids == {"vid001", "vid003"}

    def test_filter_no_results(self, sample_videos: list[dict]) -> None:
        """Filter with no matches returns empty list."""
        vf = VideoFilter(keyword="존재하지않는과목")
        result = VideoFilterService.filter_videos(sample_videos, vf)
        assert result == []

    def test_filter_by_video_ids(self, sample_videos: list[dict]) -> None:
        """Video IDs filter returns only specified videos."""
        vf = VideoFilter(video_ids=["vid002", "vid004"])
        result = VideoFilterService.filter_videos(sample_videos, vf)
        assert len(result) == 2
        video_ids = {v["video_id"] for v in result}
        assert video_ids == {"vid002", "vid004"}

    def test_invalid_date_excluded(self) -> None:
        """Videos with non-ISO published_at are excluded by date filters."""
        from datetime import date

        videos = [
            {"video_id": "good", "title": "Valid",
             "published_at": "2026-02-01T00:00:00Z"},
            {"video_id": "bad1", "title": "Invalid partial",
             "published_at": "2026-02-XX"},
            {"video_id": "bad2", "title": "Invalid empty", "published_at": ""},
        ]
        vf = VideoFilter(
            published_after=date(2026, 1, 1),
            published_before=date(2026, 12, 31),
        )
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1
        assert result[0]["video_id"] == "good"

    def test_video_ids_csv_whitespace_stripped(self) -> None:
        """Video IDs with surrounding whitespace should still match."""
        videos = [
            {"video_id": "vid001", "title": "A",
             "published_at": "2026-01-01T00:00:00Z"},
            {"video_id": "vid002", "title": "B",
             "published_at": "2026-01-01T00:00:00Z"},
        ]
        vf = VideoFilter(video_ids=["vid001", " vid002"])
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 2


class TestSortVideos:
    """Tests for VideoFilterService.sort_videos() (T032)."""

    def setup_method(self) -> None:
        """Create test videos with varied dates, titles, and views."""
        self.videos = [
            {
                "video_id": "v1",
                "title": "감염미생물학 3주차 1차시",
                "published_at": "2026-01-10T00:00:00Z",
                "view_count": 50,
            },
            {
                "video_id": "v2",
                "title": "감염미생물학 1주차 2차시",
                "published_at": "2026-03-15T00:00:00Z",
                "view_count": 200,
            },
            {
                "video_id": "v3",
                "title": "인체구조와기능 2주차 1차시",
                "published_at": "2026-02-20T00:00:00Z",
                "view_count": 100,
            },
            {
                "video_id": "v4",
                "title": "감염미생물학 1주차 1차시",
                "published_at": "2026-01-05T00:00:00Z",
                "view_count": 300,
            },
        ]

    def test_sort_by_date_newest_first(self) -> None:
        """Sort by date returns newest first."""
        result = VideoFilterService.sort_videos(self.videos, "date")
        ids = [v["video_id"] for v in result]
        assert ids == ["v2", "v3", "v1", "v4"]

    def test_sort_by_views_descending(self) -> None:
        """Sort by views returns highest view count first."""
        result = VideoFilterService.sort_videos(self.videos, "views")
        ids = [v["video_id"] for v in result]
        assert ids == ["v4", "v2", "v3", "v1"]

    def test_sort_by_course_groups_by_subject(self) -> None:
        """Sort by course groups by subject name, then week, then session."""
        result = VideoFilterService.sort_videos(self.videos, "course")
        ids = [v["video_id"] for v in result]
        # 감염미생물학 1주차 1차시 → 감염미생물학 1주차 2차시
        # → 감염미생물학 3주차 1차시 → 인체구조와기능 2주차 1차시
        assert ids == ["v4", "v2", "v1", "v3"]

    def test_sort_default_is_date(self) -> None:
        """Unknown sort_by value falls back to date sort."""
        result = VideoFilterService.sort_videos(self.videos, "unknown")
        ids = [v["video_id"] for v in result]
        assert ids == ["v2", "v3", "v1", "v4"]


class TestSpecialCharKeyword:
    """Tests for keyword with special characters (T041)."""

    def test_keyword_with_parentheses(self) -> None:
        """Keyword containing parentheses matches correctly."""
        videos = [
            {"video_id": "v1", "title": "해부학(1) 강의",
             "published_at": "2026-01-01T00:00:00Z"},
            {"video_id": "v2", "title": "해부학 강의",
             "published_at": "2026-01-01T00:00:00Z"},
        ]
        vf = VideoFilter(keyword="해부학(1)")
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1
        assert result[0]["video_id"] == "v1"

    def test_keyword_with_quotes(self) -> None:
        """Keyword containing quotes matches correctly."""
        videos = [
            {"video_id": "v1", "title": '해부학 "심화" 과정',
             "published_at": "2026-01-01T00:00:00Z"},
            {"video_id": "v2", "title": "해부학 기초",
             "published_at": "2026-01-01T00:00:00Z"},
        ]
        vf = VideoFilter(keyword='"심화"')
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1
        assert result[0]["video_id"] == "v1"

    def test_keyword_with_ampersand(self) -> None:
        """Keyword containing & matches correctly."""
        videos = [
            {"video_id": "v1", "title": "A&P 해부학 강의",
             "published_at": "2026-01-01T00:00:00Z"},
            {"video_id": "v2", "title": "해부학 강의",
             "published_at": "2026-01-01T00:00:00Z"},
        ]
        vf = VideoFilter(keyword="A&P")
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1
        assert result[0]["video_id"] == "v1"

    def test_keyword_with_brackets(self) -> None:
        """Keyword containing brackets matches correctly."""
        videos = [
            {"video_id": "v1", "title": "[특강] 미생물학",
             "published_at": "2026-01-01T00:00:00Z"},
            {"video_id": "v2", "title": "미생물학 정규",
             "published_at": "2026-01-01T00:00:00Z"},
        ]
        vf = VideoFilter(keyword="[특강]")
        result = VideoFilterService.filter_videos(videos, vf)
        assert len(result) == 1
        assert result[0]["video_id"] == "v1"
