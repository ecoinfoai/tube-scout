"""LLM-based transcript segmentation and difficulty scoring service."""

from typing import Any


class SegmenterService:
    """Service for segmenting transcripts into chapters with difficulty scores."""

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
        """
        # [VERIFY] This will be connected to actual LLM API (Anthropic/OpenAI)
        raise NotImplementedError(
            "LLM backend requires API configuration. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."
        )


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
