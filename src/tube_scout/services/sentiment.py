"""Sentiment analysis service for comment analysis."""

import hashlib
import json
import os
from typing import Any

from pydantic import BaseModel, Field

LLM_BATCH_SIZE = 20

# --- Pydantic schemas for structured LLM output ---


class SentimentResult(BaseModel):
    """Single comment sentiment analysis result."""

    comment_id: str
    sentiment: str = Field(description="One of: positive, neutral, negative")
    confidence: float = Field(ge=0.0, le=1.0)
    topics: list[str] = Field(default_factory=list)
    is_question: bool = False


class SentimentBatchResult(BaseModel):
    """Batch of sentiment analysis results."""

    results: list[SentimentResult]


# --- Label mapping for local Korean NLP models ---

_KOREAN_LABEL_MAP: dict[str, str] = {
    "긍정": "positive",
    "부정": "negative",
    "중립": "neutral",
    "LABEL_0": "negative",
    "LABEL_1": "neutral",
    "LABEL_2": "positive",
    "POSITIVE": "positive",
    "NEGATIVE": "negative",
    "NEUTRAL": "neutral",
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
}

# Module-level cache for lazy-loaded local pipeline
_local_pipeline: Any = None


def _load_local_pipeline() -> Any:
    """Lazy-load the local transformers sentiment pipeline.

    Returns:
        A transformers pipeline callable.

    Raises:
        ImportError: If transformers is not installed.
    """
    global _local_pipeline
    if _local_pipeline is not None:
        return _local_pipeline

    from transformers import pipeline  # type: ignore[import-untyped]

    from tube_scout.models.config import get_device

    device = get_device()
    _local_pipeline = pipeline(
        "sentiment-analysis",
        model="snunlp/KR-FinBert-SC",
        device=device,
    )
    return _local_pipeline


_SENTIMENT_SYSTEM_PROMPT = """\
You are a comment sentiment analyzer for educational lecture videos.
Analyze each comment and return structured JSON.

For each comment, determine:
- sentiment: "positive", "neutral", or "negative"
- confidence: 0.0 to 1.0 confidence score
- topics: list of topic keywords found in the comment
- is_question: whether the comment is asking a question

Handle comments in any language including Korean, English, or mixed.
Return a JSON object with a "results" array containing one entry per comment.
Each entry must have: comment_id, sentiment, confidence, topics, is_question.
"""


class SentimentService:
    """Service for analyzing comment sentiment, topics, and questions.

    Supports multiple backends: 'llm', 'local', 'skip'.
    """

    def __init__(self, backend: str = "llm") -> None:
        """Initialize with the specified analysis backend.

        Args:
            backend: Analysis backend ('llm', 'local', or 'skip').

        Raises:
            ValueError: If backend is not supported.
        """
        valid_backends = {"llm", "local", "skip"}
        if backend not in valid_backends:
            raise ValueError(
                f"Unsupported sentiment backend: '{backend}'. "
                f"Supported: {sorted(valid_backends)}"
            )
        self.backend = backend
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._llm_adapter: Any = None

    def analyze_batch(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze a batch of comments for sentiment, topics, and questions.

        Args:
            comments: List of comment dicts with 'comment_id' and 'text'.

        Returns:
            List of analysis result dicts.

        Raises:
            ValueError: If backend is unavailable (missing API key or library).
        """
        if not comments:
            return []

        if self.backend == "skip":
            return [
                {
                    "comment_id": c["comment_id"],
                    "sentiment": None,
                    "confidence": 0.0,
                    "topics": [],
                    "is_question": False,
                }
                for c in comments
            ]

        # Check cache
        cache_key = self._compute_cache_key(comments)
        if cache_key in self._cache:
            return self._cache[cache_key]

        if self.backend == "llm":
            results = self._analyze_llm(comments)
        elif self.backend == "local":
            results = self._analyze_local(comments)
        else:
            raise ValueError(f"Unsupported sentiment backend: '{self.backend}'")

        self._cache[cache_key] = results
        return results

    def _analyze_llm(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze comments using LLM backend.

        Args:
            comments: List of comment dicts.

        Returns:
            List of analysis results.

        Raises:
            ValueError: If LLM adapter is not configured and no API key found.
        """
        if self._llm_adapter is None:
            self._llm_adapter = self._create_llm_adapter()

        all_results: list[dict[str, Any]] = []
        batch_size = LLM_BATCH_SIZE
        for i in range(0, len(comments), batch_size):
            batch = comments[i : i + batch_size]
            batch_results = self._call_llm_batch(batch)
            all_results.extend(batch_results)

        return all_results

    def _create_llm_adapter(self) -> Any:
        """Create an LLMAdapter instance for sentiment analysis.

        Returns:
            An LLMAdapter instance.

        Raises:
            ValueError: If no API key is available.
        """
        api_key_vars = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
        has_key = any(os.environ.get(var) for var in api_key_vars)
        if not has_key:
            raise ValueError(
                "LLM sentiment backend requires an API key. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY, "
                "or use --sentiment-backend local"
            )

        from tube_scout.services.llm_adapter import LLMAdapter

        return LLMAdapter()

    def _call_llm_batch(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Call LLM for a single batch of comments.

        Args:
            comments: Batch of comment dicts (max 20).

        Returns:
            List of analysis result dicts.
        """
        comment_data = json.dumps(
            [{"comment_id": c["comment_id"], "text": c["text"]} for c in comments],
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = f"Analyze these comments:\n{comment_data}"

        response = self._llm_adapter.complete_json(
            system_prompt=_SENTIMENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=SentimentBatchResult,
        )
        return [r for r in response.model_dump()["results"]]

    def _analyze_local(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analyze comments using local NLP pipeline.

        Args:
            comments: List of comment dicts.

        Returns:
            List of analysis results.

        Raises:
            ValueError: If transformers library is not available.
        """
        try:
            pipe = _load_local_pipeline()
        except ImportError:
            raise ValueError(
                "Local sentiment backend requires the transformers + torch "
                "stack, which is shipped as an optional extra. "
                "Install with: uv sync --extra ml-sentiment "
                "(or: pip install 'tube-scout[ml-sentiment]')."
            )

        texts = [c["text"] for c in comments]
        raw_results = pipe(texts, truncation=True, max_length=512)

        results: list[dict[str, Any]] = []
        for comment, raw in zip(comments, raw_results):
            label = _KOREAN_LABEL_MAP.get(raw["label"], "neutral")
            results.append(
                {
                    "comment_id": comment["comment_id"],
                    "sentiment": label,
                    "confidence": round(raw["score"], 4),
                    "topics": [],
                    "is_question": False,
                }
            )
        return results

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

    Links question topics to hotspot time ranges with relevance scoring.
    Relevance score is based on the hotspot's audience watch ratio
    normalized to a 0.0-1.0 range.

    Args:
        questions: List of comments flagged as questions (with topics).
        hotspots: List of retention hotspot data points with
            'elapsed_ratio' and 'audience_watch_ratio'.

    Returns:
        List of cross-reference entries linking topics to time ranges,
        each with a relevance_score (0.0-1.0).
    """
    if not questions or not hotspots:
        return []

    # Find max watch ratio for normalization
    max_ratio = max(h["audience_watch_ratio"] for h in hotspots)
    max_ratio = max(max_ratio, 1.0)  # avoid division by zero

    results = []
    for hotspot in hotspots:
        related_topics: list[str] = []
        for q in questions:
            related_topics.extend(q.get("topics", []))

        if related_topics:
            relevance = min(1.0, hotspot["audience_watch_ratio"] / max_ratio)
            results.append(
                {
                    "elapsed_ratio": hotspot["elapsed_ratio"],
                    "audience_watch_ratio": hotspot["audience_watch_ratio"],
                    "related_topics": list(set(related_topics)),
                    "question_count": len(questions),
                    "relevance_score": round(relevance, 4),
                }
            )

    return results
