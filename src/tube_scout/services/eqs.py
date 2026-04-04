"""Education Quality Scoring (EQS) service — RACED 5-axis evaluation."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema for LLM JSON output
# ---------------------------------------------------------------------------

class _RACEDScores(BaseModel):
    """Schema for RACED 5-axis scores returned by the LLM."""

    relevance: float = Field(ge=0.0, le=1.0)
    accuracy: float = Field(ge=0.0, le=1.0)
    clarity: float = Field(ge=0.0, le=1.0)
    engagement: float = Field(ge=0.0, le=1.0)
    depth: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert educational video quality evaluator. Evaluate the \
given video transcript on 5 RACED axes, each scored 0.0 to 1.0:

- Relevance: How well the content matches the stated topic
- Accuracy: Factual correctness and up-to-date information
- Clarity: How clearly concepts are explained (structure, examples)
- Engagement: How engaging the delivery is (pacing, interaction)
- Depth: Level of analytical and conceptual depth

Use retention data (audience watch ratios) and viewer comments as \
additional signals for Engagement and Clarity.

Return a JSON object with exactly these keys: relevance, accuracy, \
clarity, engagement, depth. Each value must be a float between \
0.0 and 1.0. Do NOT include any text outside the JSON object."""


class EQSService:
    """Service for evaluating video education quality using RACED 5-axis model."""

    def __init__(self, llm: Any | None = None) -> None:
        """Initialize EQS service with optional LLM adapter.

        Args:
            llm: LLMAdapter instance. If None, evaluate will raise
                NotImplementedError when called on non-empty transcripts.
        """
        self._llm = llm

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

        Raises:
            NotImplementedError: If no LLM adapter is configured.
            ValueError: If LLM response cannot be parsed after retries.
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

        scores = self._call_llm(
            transcript_text, retention_data, comment_data,
        )
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
            ValueError: If LLM response cannot be parsed.
        """
        if self._llm is None:
            raise NotImplementedError(
                "LLM backend requires API configuration. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY "
                "environment variable."
            )

        retention_summary = json.dumps(
            retention_data[:20], indent=None,
        ) if retention_data else "No retention data available."

        comment_summary = json.dumps(
            comment_data[:20], indent=None,
        ) if comment_data else "No comment data available."

        user_prompt = (
            f"Evaluate the following video transcript:\n\n"
            f"{transcript_text}\n\n"
            f"--- Retention / watch data ---\n"
            f"{retention_summary}\n\n"
            f"--- Viewer comments / feedback ---\n"
            f"{comment_summary}"
        )

        result: _RACEDScores = self._llm.complete_json(
            _SYSTEM_PROMPT,
            user_prompt,
            _RACEDScores,
        )

        return result.model_dump()
