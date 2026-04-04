"""Unit tests for VideoFilter model."""

from datetime import date

import pytest
from pydantic import ValidationError

from tube_scout.models.video_filter import VideoFilter


class TestVideoFilter:
    """Tests for VideoFilter Pydantic model validation."""

    def test_empty_filter_rejected(self) -> None:
        """All fields None must raise ValidationError."""
        with pytest.raises(ValidationError):
            VideoFilter()

    def test_date_range_invalid(self) -> None:
        """published_after > published_before must raise ValidationError."""
        with pytest.raises(ValidationError):
            VideoFilter(
                published_after=date(2026, 4, 1),
                published_before=date(2026, 1, 1),
            )

    def test_keyword_only(self) -> None:
        """Keyword-only filter should be valid."""
        f = VideoFilter(keyword="감염미생물학")
        assert f.keyword == "감염미생물학"
        assert f.published_after is None
        assert f.published_before is None
        assert f.video_ids is None

    def test_date_range_only(self) -> None:
        """Date range only filter should be valid."""
        f = VideoFilter(
            published_after=date(2026, 1, 1),
            published_before=date(2026, 4, 1),
        )
        assert f.published_after == date(2026, 1, 1)
        assert f.published_before == date(2026, 4, 1)

    def test_video_ids_only(self) -> None:
        """Video IDs only filter should be valid."""
        f = VideoFilter(video_ids=["abc123", "def456"])
        assert f.video_ids == ["abc123", "def456"]

    def test_combined_filter(self) -> None:
        """Keyword + date range combined filter should be valid."""
        f = VideoFilter(
            keyword="인체구조와기능",
            published_after=date(2026, 1, 1),
            published_before=date(2026, 4, 1),
        )
        assert f.keyword == "인체구조와기능"
        assert f.published_after == date(2026, 1, 1)
        assert f.published_before == date(2026, 4, 1)

    def test_empty_keyword_treated_as_none(self) -> None:
        """Empty string keyword should be treated as no filter (rejected)."""
        with pytest.raises(ValidationError):
            VideoFilter(keyword="")
