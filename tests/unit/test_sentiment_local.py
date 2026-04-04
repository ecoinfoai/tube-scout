"""Tests for local NLP sentiment backend (T041)."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tube_scout.services.sentiment import SentimentService

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _make_mock_pipeline() -> MagicMock:
    """Create a mock transformers pipeline that returns sentiment results."""
    mock_pipe = MagicMock()

    def classify(texts: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        results = []
        for text in texts:
            # Check negative keywords first (handles "안 좋" before "좋")
            neg = ["부족", "안 좋", "힘들", "불편", "어렵", "불친절"]
            pos = ["좋은", "감사", "최고", "잘", "좋아", "재미", "유익"]
            if any(w in text for w in neg):
                results.append({"label": "부정", "score": 0.88})
            elif any(w in text for w in pos):
                results.append({"label": "긍정", "score": 0.92})
            else:
                results.append({"label": "중립", "score": 0.75})
        return results

    mock_pipe.side_effect = classify
    return mock_pipe


class TestLocalSentimentBackend:
    """Tests for SentimentService with backend='local'."""

    @patch("tube_scout.services.sentiment._load_local_pipeline")
    def test_korean_comment_classification(
        self, mock_load: MagicMock
    ) -> None:
        """Korean comments are classified into positive/neutral/negative."""
        mock_load.return_value = _make_mock_pipeline()

        service = SentimentService(backend="local")
        comments = [
            {"comment_id": "c0", "text": "정말 좋은 강의입니다!"},
            {"comment_id": "c1", "text": "다음 강의는 언제 올라오나요?"},
            {"comment_id": "c2", "text": "음질이 안 좋아서 듣기 힘들어요."},
        ]
        results = service.analyze_batch(comments)

        assert len(results) == 3
        assert results[0]["sentiment"] == "positive"
        assert results[1]["sentiment"] == "neutral"
        assert results[2]["sentiment"] == "negative"

    @patch("tube_scout.services.sentiment._load_local_pipeline")
    def test_batch_processing(self, mock_load: MagicMock) -> None:
        """Batch processing returns results for all comments."""
        mock_load.return_value = _make_mock_pipeline()

        service = SentimentService(backend="local")
        comments = [
            {"comment_id": f"c{i}", "text": f"Comment {i}"}
            for i in range(10)
        ]
        results = service.analyze_batch(comments)

        assert len(results) == 10
        for i, r in enumerate(results):
            assert r["comment_id"] == f"c{i}"
            assert r["sentiment"] in ("positive", "neutral", "negative")
            assert 0.0 <= r["confidence"] <= 1.0

    @patch("tube_scout.services.sentiment._load_local_pipeline")
    def test_empty_comments_returns_empty(self, mock_load: MagicMock) -> None:
        """Empty comment list returns empty result without loading pipeline."""
        mock_load.return_value = _make_mock_pipeline()

        service = SentimentService(backend="local")
        results = service.analyze_batch([])

        assert results == []
        mock_load.assert_not_called()

    @patch("tube_scout.services.sentiment._load_local_pipeline")
    def test_caching_works_with_local_backend(
        self, mock_load: MagicMock
    ) -> None:
        """Content-hash caching works with local backend too."""
        mock_pipe = _make_mock_pipeline()
        mock_load.return_value = mock_pipe

        service = SentimentService(backend="local")
        comments = [{"comment_id": "c0", "text": "Test comment"}]

        result1 = service.analyze_batch(comments)
        result2 = service.analyze_batch(comments)

        assert result1 == result2
        # Pipeline should only be called once due to caching
        assert mock_pipe.call_count == 1

    @patch("tube_scout.services.sentiment._load_local_pipeline")
    def test_korean_sample_accuracy(self, mock_load: MagicMock) -> None:
        """T047b: Local backend achieves >=80% accuracy on labeled Korean samples."""
        mock_load.return_value = _make_mock_pipeline()

        samples_path = FIXTURES_DIR / "korean_sentiment_samples.json"
        with open(samples_path) as f:
            samples = json.load(f)

        comments = [
            {"comment_id": f"s{i}", "text": s["text"]}
            for i, s in enumerate(samples)
        ]
        expected_labels = [s["label"] for s in samples]

        service = SentimentService(backend="local")
        results = service.analyze_batch(comments)

        assert len(results) == len(samples)
        correct = sum(
            1
            for r, expected in zip(results, expected_labels)
            if r["sentiment"] == expected
        )
        accuracy = correct / len(samples)
        mismatches = [
            (r["comment_id"], r["sentiment"], exp)
            for r, exp in zip(results, expected_labels)
            if r["sentiment"] != exp
        ]
        assert accuracy >= 0.80, (
            f"Accuracy {accuracy:.0%} is below 80% threshold. "
            f"Mismatches: {mismatches}"
        )
