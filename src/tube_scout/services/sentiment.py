"""Sentiment analysis service for comment analysis."""

import hashlib
import json
from typing import Any


class SentimentService:
    """Service for analyzing comment sentiment, topics, and questions.

    Supports multiple backends: 'llm', 'local', 'skip'.
    """

    def __init__(self, backend: str = "llm") -> None:
        """Initialize with the specified analysis backend.

        Args:
            backend: Analysis backend ('llm', 'local', or 'skip').
        """
        self.backend = backend
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def analyze_batch(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze a batch of comments for sentiment, topics, and questions.

        Args:
            comments: List of comment dicts with 'comment_id' and 'text'.

        Returns:
            List of analysis result dicts.
        """
        if self.backend == "skip":
            return [
                {
                    "comment_id": c["comment_id"],
                    "sentiment": None,
                    "topics": [],
                    "is_question": False,
                }
                for c in comments
            ]

        # Check cache
        cache_key = self._compute_cache_key(comments)
        if cache_key in self._cache:
            return self._cache[cache_key]

        results = self._call_llm(comments)
        self._cache[cache_key] = results
        return results

    def _call_llm(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Call LLM API for batch comment analysis.

        Args:
            comments: List of comment dicts.

        Returns:
            List of analysis results.

        Raises:
            NotImplementedError: When no LLM client is configured.
        """
        # [VERIFY] This will be connected to actual LLM API (Anthropic/OpenAI)
        raise NotImplementedError(
            "LLM backend requires API configuration. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."
        )

    def _compute_cache_key(self, comments: list[dict[str, Any]]) -> str:
        """Compute a hash key for a batch of comments.

        Args:
            comments: List of comment dicts.

        Returns:
            Hex digest string.
        """
        content = json.dumps(
            [{"id": c["comment_id"], "text": c["text"]} for c in comments],
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()


def cross_reference_questions_hotspots(
    questions: list[dict[str, Any]],
    hotspots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-reference comment questions with retention hotspots.

    Args:
        questions: List of comments flagged as questions (with topics).
        hotspots: List of retention hotspot data points.

    Returns:
        List of cross-reference entries linking topics to time ranges.
    """
    if not questions or not hotspots:
        return []

    results = []
    for hotspot in hotspots:
        related_topics: list[str] = []
        for q in questions:
            related_topics.extend(q.get("topics", []))

        if related_topics:
            results.append(
                {
                    "elapsed_ratio": hotspot["elapsed_ratio"],
                    "audience_watch_ratio": hotspot["audience_watch_ratio"],
                    "related_topics": list(set(related_topics)),
                    "question_count": len(questions),
                }
            )

    return results
