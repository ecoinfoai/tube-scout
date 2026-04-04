"""Topic extraction and question identification service."""

import json
import os
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

# --- Pydantic schemas for structured LLM output ---


class TopicAnalysisResult(BaseModel):
    """Single comment topic analysis result from LLM."""

    comment_id: str
    topic_label: str = Field(description="Auto-generated topic name")
    sentiment: str = Field(description="One of: positive, neutral, negative")
    confidence: float = Field(ge=0.0, le=1.0)
    is_question: bool = False
    question_text: str | None = None


class TopicBatchResult(BaseModel):
    """Batch of topic analysis results."""

    results: list[TopicAnalysisResult]


_TOPIC_SYSTEM_PROMPT = """\
You are a topic and question extractor for educational lecture video comments.
Analyze each comment and return structured JSON.

For each comment, determine:
- topic_label: a short topic name that categorizes the comment (e.g., "audio quality", \
"exam schedule", "teaching style", "content difficulty")
- sentiment: "positive", "neutral", or "negative"
- confidence: 0.0 to 1.0 confidence score
- is_question: whether the comment is asking a question
- question_text: if is_question, extract question text verbatim; null otherwise

Group similar concepts under the same topic_label for clustering.
Handle comments in any language including Korean, English, or mixed.
Return a JSON object with a "results" array containing one entry per comment.
"""


class TopicExtractorService:
    """Service for extracting topics and questions from comments.

    Uses LLM-based topic extraction with structured output.
    Clusters comments by topic and cross-references questions with
    retention hotspots.
    """

    def __init__(self) -> None:
        """Initialize the topic extractor service."""
        self._llm_adapter: Any = None

    def extract_topics(
        self, video_id: str, comments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract topic clusters from comments.

        Args:
            video_id: Video identifier.
            comments: List of comment dicts with 'comment_id' and 'text'.

        Returns:
            List of TopicCluster dicts with topic_label, comment_ids,
            sentiment_distribution, and representative_comments.

        Raises:
            ValueError: If LLM adapter cannot be created (missing API key).
        """
        if not comments:
            return []

        raw_results = self._analyze_comments(comments)
        return self._build_clusters(video_id, comments, raw_results)

    def extract_questions(
        self, video_id: str, comments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract questions from comments.

        Args:
            video_id: Video identifier.
            comments: List of comment dicts with 'comment_id' and 'text'.

        Returns:
            List of question dicts with comment_id and question_text.

        Raises:
            ValueError: If LLM adapter cannot be created (missing API key).
        """
        if not comments:
            return []

        raw_results = self._analyze_comments(comments)
        questions: list[dict[str, Any]] = []
        for r in raw_results:
            if r["is_question"] and r.get("question_text"):
                questions.append({
                    "comment_id": r["comment_id"],
                    "question_text": r["question_text"],
                })
        return questions

    def cross_reference_with_hotspots(
        self,
        video_id: str,
        comments: list[dict[str, Any]],
        hotspots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Cross-reference extracted questions with retention hotspots.

        Args:
            video_id: Video identifier.
            comments: List of comment dicts with 'comment_id' and 'text'.
            hotspots: List of retention hotspot dicts with 'elapsed_ratio'
                and 'audience_watch_ratio'.

        Returns:
            List of QuestionMatch dicts with video_id, comment_id,
            question_text, matched_hotspot_start, matched_hotspot_end,
            and relevance_score.
        """
        if not comments or not hotspots:
            return []

        questions = self.extract_questions(video_id, comments)
        if not questions:
            return []

        matches: list[dict[str, Any]] = []
        for question in questions:
            best_hotspot = max(hotspots, key=lambda h: h["audience_watch_ratio"])
            ratio = best_hotspot["elapsed_ratio"]
            # Create a small window around the hotspot
            window = 0.05
            matches.append({
                "video_id": video_id,
                "comment_id": question["comment_id"],
                "question_text": question["question_text"],
                "matched_hotspot_start": max(0.0, ratio - window),
                "matched_hotspot_end": min(1.0, ratio + window),
                "relevance_score": min(
                    1.0,
                    best_hotspot["audience_watch_ratio"] / 2.0,
                ),
            })

        return matches

    def _analyze_comments(
        self, comments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Analyze comments via LLM in batches of 20.

        Args:
            comments: List of comment dicts.

        Returns:
            List of per-comment analysis result dicts.

        Raises:
            ValueError: If LLM adapter cannot be created.
        """
        if self._llm_adapter is None:
            self._llm_adapter = self._create_llm_adapter()

        all_results: list[dict[str, Any]] = []
        batch_size = 20
        for i in range(0, len(comments), batch_size):
            batch = comments[i : i + batch_size]
            batch_results = self._call_llm_batch(batch)
            all_results.extend(batch_results)

        return all_results

    def _create_llm_adapter(self) -> Any:
        """Create an LLMAdapter instance.

        Returns:
            An LLMAdapter instance.

        Raises:
            ValueError: If no API key is available.
        """
        api_key_vars = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
        has_key = any(os.environ.get(var) for var in api_key_vars)
        if not has_key:
            raise ValueError(
                "Topic extraction requires an API key. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
            )

        from tube_scout.services.llm_adapter import LLMAdapter

        return LLMAdapter()

    def _call_llm_batch(
        self, comments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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
            system_prompt=_TOPIC_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=TopicBatchResult,
        )
        return response.model_dump()["results"]

    def _build_clusters(
        self,
        video_id: str,
        comments: list[dict[str, Any]],
        raw_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build TopicCluster dicts from raw per-comment results.

        Args:
            video_id: Video identifier.
            comments: Original comment dicts (for representative texts).
            raw_results: Per-comment analysis results from LLM.

        Returns:
            List of TopicCluster dicts.
        """
        # Build a lookup for comment text
        text_by_id: dict[str, str] = {
            c["comment_id"]: c["text"] for c in comments
        }

        # Group by topic_label
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in raw_results:
            groups[r["topic_label"]].append(r)

        clusters: list[dict[str, Any]] = []
        for topic_label, members in groups.items():
            comment_ids = [m["comment_id"] for m in members]

            # Compute sentiment distribution
            sentiment_counts: dict[str, int] = {
                "positive": 0,
                "neutral": 0,
                "negative": 0,
            }
            for m in members:
                s = m.get("sentiment", "neutral")
                if s in sentiment_counts:
                    sentiment_counts[s] += 1

            total = sum(sentiment_counts.values()) or 1
            sentiment_distribution = {
                k: round(v / total, 4) for k, v in sentiment_counts.items()
            }

            # Pick up to 3 representative comments
            representative = [
                text_by_id[cid]
                for cid in comment_ids[:3]
                if cid in text_by_id
            ]

            clusters.append({
                "video_id": video_id,
                "topic_label": topic_label,
                "comment_ids": comment_ids,
                "sentiment_distribution": sentiment_distribution,
                "representative_comments": representative,
            })

        return clusters
