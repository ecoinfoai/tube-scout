"""Channel data model."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Channel(BaseModel):
    """YouTube channel data model."""

    channel_id: str = Field(..., min_length=1)
    channel_name: str
    uploads_playlist_id: str = ""
    professor_name: str
    total_video_count: int = 0
    filtered_video_count: int = 0
    last_collected_at: datetime | None = None

    @field_validator("channel_id")
    @classmethod
    def channel_id_must_start_with_uc(cls, v: str) -> str:
        """Validate that channel_id starts with 'UC'."""
        if not v.startswith("UC"):
            raise ValueError("channel_id must start with 'UC'")
        return v

    def model_post_init(self, __context: object) -> None:
        """Auto-derive uploads_playlist_id from channel_id."""
        if not self.uploads_playlist_id and self.channel_id.startswith("UC"):
            self.uploads_playlist_id = "UU" + self.channel_id[2:]
