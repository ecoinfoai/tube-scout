"""Tests for SentimentService."""

from unittest.mock import patch

import pytest

from tube_scout.services.sentiment import (
    SentimentService,
    cross_reference_questions_hotspots,
)


@pytest.fixture
def mock_llm_response() -> dict:
    """Sample LLM analysis response for a batch of comments."""
    return {
        "results": [
            {
                "comment_id": "c1",
                "sentiment": "positive",
                "topics": ["teaching quality"],
                "is_question": False,
            },
            {
                "comment_id": "c2",
                "sentiment": "neutral",
                "topics": ["exam", "schedule"],
                "is_question": True,
            },
            {
                "comment_id": "c3",
                "sentiment": "negative",
                "topics": ["audio quality"],
                "is_question": False,
            },
        ]
    }


class TestSentimentService:
    """Tests for SentimentService (T036)."""

    def test_analyze_batch_returns_results(self, mock_llm_response: dict) -> None:
        service = SentimentService(backend="llm")
        comments = [
            {"comment_id": "c1", "text": "Great lecture, very clear!"},
            {"comment_id": "c2", "text": "When is the exam?"},
            {"comment_id": "c3", "text": "Audio is terrible"},
        ]
        with patch.object(
            service, "_call_llm", return_value=mock_llm_response["results"]
        ):
            results = service.analyze_batch(comments)
        assert len(results) == 3
        assert results[0]["sentiment"] == "positive"
        assert results[1]["is_question"] is True

    def test_caching_by_content_hash(self) -> None:
        service = SentimentService(backend="llm")
        comments = [{"comment_id": "c1", "text": "Same text"}]
        mock_result = [
            {
                "comment_id": "c1",
                "sentiment": "neutral",
                "topics": [],
                "is_question": False,
            }
        ]

        with patch.object(service, "_call_llm", return_value=mock_result) as mock_call:
            result1 = service.analyze_batch(comments)
            result2 = service.analyze_batch(comments)

        # LLM should only be called once due to caching
        assert mock_call.call_count == 1
        assert result1 == result2

    def test_skip_backend(self) -> None:
        service = SentimentService(backend="skip")
        comments = [
            {"comment_id": "c1", "text": "Some comment"},
        ]
        results = service.analyze_batch(comments)
        assert len(results) == 1
        assert results[0]["sentiment"] is None

    def test_backend_switching(self) -> None:
        service_llm = SentimentService(backend="llm")
        assert service_llm.backend == "llm"

        service_local = SentimentService(backend="local")
        assert service_local.backend == "local"

        service_skip = SentimentService(backend="skip")
        assert service_skip.backend == "skip"


class TestCrossReferenceQuestionsHotspots:
    """Tests for cross_reference_questions_hotspots (FR-011a)."""

    def test_links_topics_to_hotspots(self) -> None:
        questions = [
            {
                "comment_id": "c1",
                "text": "What is mitosis?",
                "topics": ["cell division", "mitosis"],
                "is_question": True,
            },
            {
                "comment_id": "c2",
                "text": "How does meiosis differ?",
                "topics": ["meiosis"],
                "is_question": True,
            },
        ]
        hotspots = [
            {"elapsed_ratio": 0.3, "audience_watch_ratio": 1.5},
            {"elapsed_ratio": 0.7, "audience_watch_ratio": 1.8},
        ]
        results = cross_reference_questions_hotspots(questions, hotspots)
        assert len(results) == 2
        # Each hotspot should have related_topics from all questions
        assert "elapsed_ratio" in results[0]
        assert "audience_watch_ratio" in results[0]
        assert "related_topics" in results[0]
        assert "question_count" in results[0]
        assert results[0]["question_count"] == 2
        # Topics should be deduplicated
        all_topics = set()
        for r in results:
            all_topics.update(r["related_topics"])
        assert "cell division" in all_topics
        assert "mitosis" in all_topics
        assert "meiosis" in all_topics

    def test_empty_questions(self) -> None:
        hotspots = [
            {"elapsed_ratio": 0.5, "audience_watch_ratio": 1.3},
        ]
        results = cross_reference_questions_hotspots([], hotspots)
        assert results == []

    def test_empty_hotspots(self) -> None:
        questions = [
            {
                "comment_id": "c1",
                "text": "Question?",
                "topics": ["topic"],
                "is_question": True,
            },
        ]
        results = cross_reference_questions_hotspots(questions, [])
        assert results == []
