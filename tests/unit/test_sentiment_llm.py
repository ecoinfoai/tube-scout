"""Tests for LLM sentiment backend (T040)."""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from tube_scout.services.sentiment import SentimentService


@pytest.fixture
def mock_adapter() -> MagicMock:
    """Create a mock LLMAdapter that returns structured sentiment results."""
    adapter = MagicMock()
    return adapter


def _make_comments(n: int = 3) -> list[dict[str, Any]]:
    """Generate a list of test comments."""
    texts = [
        "Great lecture, very clear!",
        "When is the exam?",
        "Audio is terrible",
        "정말 좋은 강의입니다!",
        "이해가 안 됩니다.",
    ]
    return [{"comment_id": f"c{i}", "text": texts[i % len(texts)]} for i in range(n)]


class TestLLMSentimentBackend:
    """Tests for SentimentService with backend='llm'."""

    def test_single_comment_returns_label_and_confidence(
        self, mock_adapter: MagicMock
    ) -> None:
        """Single comment analysis returns label + confidence."""
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "results": [
                {
                    "comment_id": "c0",
                    "sentiment": "positive",
                    "confidence": 0.95,
                    "topics": ["teaching quality"],
                    "is_question": False,
                }
            ]
        }
        mock_adapter.complete_json.return_value = mock_result

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        comments = [{"comment_id": "c0", "text": "Great lecture!"}]
        results = service.analyze_batch(comments)

        assert len(results) == 1
        assert results[0]["sentiment"] in ("positive", "neutral", "negative")
        assert 0.0 <= results[0]["confidence"] <= 1.0
        assert results[0]["comment_id"] == "c0"

    def test_batch_analysis_returns_results_for_all(
        self, mock_adapter: MagicMock
    ) -> None:
        """Batch analysis returns results for all comments."""
        comments = _make_comments(3)
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "results": [
                {
                    "comment_id": f"c{i}",
                    "sentiment": "positive",
                    "confidence": 0.9,
                    "topics": [],
                    "is_question": False,
                }
                for i in range(3)
            ]
        }
        mock_adapter.complete_json.return_value = mock_result

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        results = service.analyze_batch(comments)
        assert len(results) == 3
        for i, r in enumerate(results):
            assert r["comment_id"] == f"c{i}"

    def test_mixed_korean_english_comments(self, mock_adapter: MagicMock) -> None:
        """Mixed Korean+English comments are handled correctly."""
        comments = [
            {"comment_id": "c0", "text": "Great lecture!"},
            {"comment_id": "c1", "text": "정말 좋은 강의입니다!"},
            {"comment_id": "c2", "text": "Very helpful, 감사합니다!"},
        ]
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "results": [
                {
                    "comment_id": "c0",
                    "sentiment": "positive",
                    "confidence": 0.9,
                    "topics": ["teaching"],
                    "is_question": False,
                },
                {
                    "comment_id": "c1",
                    "sentiment": "positive",
                    "confidence": 0.85,
                    "topics": ["teaching"],
                    "is_question": False,
                },
                {
                    "comment_id": "c2",
                    "sentiment": "positive",
                    "confidence": 0.88,
                    "topics": ["gratitude"],
                    "is_question": False,
                },
            ]
        }
        mock_adapter.complete_json.return_value = mock_result

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        results = service.analyze_batch(comments)
        assert len(results) == 3
        # All should have valid sentiment labels
        for r in results:
            assert r["sentiment"] in ("positive", "neutral", "negative")

    def test_content_hash_caching_works(self, mock_adapter: MagicMock) -> None:
        """Content-hash caching prevents duplicate LLM calls."""
        comments = [{"comment_id": "c0", "text": "Test comment"}]
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "results": [
                {
                    "comment_id": "c0",
                    "sentiment": "neutral",
                    "confidence": 0.8,
                    "topics": [],
                    "is_question": False,
                }
            ]
        }
        mock_adapter.complete_json.return_value = mock_result

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        result1 = service.analyze_batch(comments)
        result2 = service.analyze_batch(comments)

        # LLM should only be called once
        assert mock_adapter.complete_json.call_count == 1
        assert result1 == result2

    def test_batch_of_20_chunking(self, mock_adapter: MagicMock) -> None:
        """Comments are processed in batches of 20."""
        comments = _make_comments(45)

        def fake_complete_json(
            system_prompt: str, user_prompt: str, schema: type
        ) -> MagicMock:
            # Parse the comment IDs from the user prompt to return matching results
            import re

            # Find all comment_id values in the prompt
            ids = re.findall(r'"comment_id":\s*"(c\d+)"', user_prompt)
            result = MagicMock()
            result.model_dump.return_value = {
                "results": [
                    {
                        "comment_id": cid,
                        "sentiment": "neutral",
                        "confidence": 0.7,
                        "topics": [],
                        "is_question": False,
                    }
                    for cid in ids
                ]
            }
            return result

        mock_adapter.complete_json.side_effect = fake_complete_json

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        results = service.analyze_batch(comments)
        assert len(results) == 45
        # Should be called 3 times: 20 + 20 + 5
        assert mock_adapter.complete_json.call_count == 3

    def test_empty_comments_returns_empty(self, mock_adapter: MagicMock) -> None:
        """Empty comment list returns empty result without calling LLM."""
        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        results = service.analyze_batch([])
        assert results == []
        mock_adapter.complete_json.assert_not_called()

    def test_benchmark_100_comments(self, mock_adapter: MagicMock) -> None:
        """T047a: 100 comments processed in under 60s (mocked LLM)."""
        comments = _make_comments(100)

        def fake_complete_json_with_delay(
            system_prompt: str, user_prompt: str, schema: type
        ) -> MagicMock:
            import re

            # Simulate realistic LLM response time (~0.5s per batch)
            time.sleep(0.5)
            ids = re.findall(r'"comment_id":\s*"(c\d+)"', user_prompt)
            result = MagicMock()
            result.model_dump.return_value = {
                "results": [
                    {
                        "comment_id": cid,
                        "sentiment": "neutral",
                        "confidence": 0.75,
                        "topics": [],
                        "is_question": False,
                    }
                    for cid in ids
                ]
            }
            return result

        mock_adapter.complete_json.side_effect = fake_complete_json_with_delay

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter

        start = time.time()
        results = service.analyze_batch(comments)
        elapsed = time.time() - start

        assert len(results) == 100
        assert elapsed < 60, f"Processing took {elapsed:.1f}s, exceeds 60s limit"
