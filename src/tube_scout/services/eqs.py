"""Education Quality Scoring (EQS) service — RACED 5-axis evaluation."""

from typing import Any


class EQSService:
    """Service for evaluating video education quality using RACED 5-axis model."""

    def evaluate(
        self,
        video_id: str,
        transcript_text: str,
        retention_data: list[dict[str, Any]],
        comment_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate video quality on RACED 5 axes.

        Args:
            video_id: YouTube video ID.
            transcript_text: Full transcript text.
            retention_data: Retention analysis data.
            comment_data: Comment analysis data.

        Returns:
            Dict with relevance, accuracy, clarity, engagement, depth, overall.
        """
        if not transcript_text.strip():
            return {
                "video_id": video_id,
                "relevance": 0.0,
                "accuracy": 0.0,
                "clarity": 0.0,
                "engagement": 0.0,
                "depth": 0.0,
                "overall": 0.0,
            }

        scores = self._call_llm(transcript_text, retention_data, comment_data)
        overall = sum(scores.values()) / len(scores) if scores else 0.0

        return {
            "video_id": video_id,
            **scores,
            "overall": overall,
        }

    def _call_llm(
        self,
        transcript_text: str,
        retention_data: list[dict[str, Any]],
        comment_data: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Call LLM for RACED evaluation.

        Args:
            transcript_text: Full transcript text.
            retention_data: Retention data.
            comment_data: Comment data.

        Returns:
            Dict with 5-axis scores.

        Raises:
            NotImplementedError: When no LLM client is configured.
        """
        # [VERIFY] This will be connected to actual LLM API
        raise NotImplementedError(
            "LLM backend requires API configuration. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."
        )
