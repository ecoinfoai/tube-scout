"""Comment data model."""

from datetime import datetime

from pydantic import BaseModel


class Comment(BaseModel):
    """YouTube comment data model with sentiment analysis results."""

    comment_id: str
    video_id: str
    author: str
    text: str
    published_at: datetime
    like_count: int = 0
    sentiment: str | None = None
    topics: list[str] = []
    is_question: bool = False
    analysis_backend: str | None = None
    analyzed_at: datetime | None = None
