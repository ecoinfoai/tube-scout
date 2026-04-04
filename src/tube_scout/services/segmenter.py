"""LLM-based transcript segmentation and difficulty scoring service."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema for LLM JSON output
# ---------------------------------------------------------------------------

class _ChapterSchema(BaseModel):
    """Schema for a single chapter produced by the LLM."""

    segment_index: int
    start_seconds: float
    end_seconds: float
    title: str
    summary: str
    difficulty_score: float = Field(ge=0.0, le=1.0)
    tags: list[str]


class _SegmentationResult(BaseModel):
    """Top-level schema for LLM segmentation response."""

    chapters: list[_ChapterSchema]


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert educational content analyst. Given a video transcript, \
divide it into semantically coherent chapters.

For each chapter provide:
- segment_index: 0-based sequential index
- start_seconds / end_seconds: approximate time boundaries
- title: short descriptive title
- summary: 1-2 sentence summary of the content
- difficulty_score: float 0.0-1.0 based on vocabulary complexity and concept density
- tags: 3-5 topic tags for the segment

If the transcript is in Korean, produce titles, summaries, and tags in Korean.

Return a JSON object with a single key "chapters" containing a list \
of chapter objects. Do NOT include any text outside the JSON object."""


class SegmenterService:
    """Service for segmenting transcripts into chapters with difficulty scores."""

    def __init__(self, llm: Any | None = None) -> None:
        """Initialize segmenter with optional LLM adapter.

        Args:
            llm: LLMAdapter instance. If None, segment_transcript will raise
                NotImplementedError when called on non-empty transcripts.
        """
        self._llm = llm

    def segment_transcript(
        self,
        video_id: str,
        transcript_text: str,
    ) -> list[dict[str, Any]]:
        """Segment a transcript into chapters with title, summary, and difficulty.

        Args:
            video_id: YouTube video ID.
            transcript_text: Full transcript text.

        Returns:
            List of segment dicts with segment_index, start_seconds, end_seconds,
            title, summary, difficulty_score, tags.

        Raises:
            NotImplementedError: If no LLM adapter is configured.
            ValueError: If LLM response cannot be parsed after retries.
        """
        if not transcript_text.strip():
            return []

        return self._call_llm(video_id, transcript_text)

    def _call_llm(self, video_id: str, transcript_text: str) -> list[dict[str, Any]]:
        """Call LLM for chapter splitting.

        Args:
            video_id: YouTube video ID.
            transcript_text: Full transcript text.

        Returns:
            List of segment dicts.

        Raises:
            NotImplementedError: When no LLM client is configured.
            ValueError: If LLM response cannot be parsed.
        """
        if self._llm is None:
            raise NotImplementedError(
                "LLM backend requires API configuration. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."
            )

        user_prompt = (
            f"Segment the following transcript for video {video_id}:\n\n"
            f"{transcript_text}"
        )

        result: _SegmentationResult = self._llm.complete_json(
            _SYSTEM_PROMPT,
            user_prompt,
            _SegmentationResult,
        )

        return [chapter.model_dump() for chapter in result.chapters]


def compare_with_retention(
    segments: list[dict[str, Any]],
    hotspots: list[dict[str, Any]],
    video_duration_seconds: int,
) -> list[dict[str, Any]]:
    """Compare predicted difficulty with actual retention hotspots.

    Args:
        segments: List of transcript segment dicts.
        hotspots: List of retention hotspot dicts.
        video_duration_seconds: Total video duration in seconds.

    Returns:
        List of comparison entries showing alignment.
    """
    if not segments or not hotspots or video_duration_seconds <= 0:
        return []

    results = []
    for segment in segments:
        seg_start_ratio = segment["start_seconds"] / video_duration_seconds
        seg_end_ratio = segment["end_seconds"] / video_duration_seconds

        overlapping_hotspots = [
            h
            for h in hotspots
            if seg_start_ratio <= h["elapsed_ratio"] <= seg_end_ratio
        ]

        results.append(
            {
                "segment_index": segment["segment_index"],
                "title": segment["title"],
                "predicted_difficulty": segment.get("difficulty_score", 0.0),
                "hotspot_count": len(overlapping_hotspots),
                "has_retention_issue": len(overlapping_hotspots) > 0,
            }
        )

    return results
