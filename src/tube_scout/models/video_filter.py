"""Video filter model for report filtering."""

from datetime import date

from pydantic import BaseModel, model_validator


class VideoFilter(BaseModel):
    """Filter criteria for selecting videos.

    At least one filter condition must be specified.
    Multiple conditions are combined with AND logic.

    Args:
        keyword: Substring match against video title.
        published_after: Inclusive start date for publish date filter.
        published_before: Inclusive end date for publish date filter.
        video_ids: Explicit list of video IDs to select.
    """

    keyword: str | None = None
    published_after: date | None = None
    published_before: date | None = None
    video_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_filter(self) -> "VideoFilter":
        """Validate that at least one condition is set and date range is valid.

        Returns:
            The validated VideoFilter instance.

        Raises:
            ValueError: If no filter condition is specified or date range is invalid.
        """
        # Treat empty/whitespace-only keyword as None
        if self.keyword is not None and not self.keyword.strip():
            raise ValueError("keyword must not be empty")

        has_any = (
            self.keyword is not None
            or self.published_after is not None
            or self.published_before is not None
            or self.video_ids is not None
        )
        if not has_any:
            raise ValueError("At least one filter condition must be specified")

        if (
            self.published_after is not None
            and self.published_before is not None
            and self.published_after > self.published_before
        ):
            raise ValueError("published_after must be <= published_before")

        return self
