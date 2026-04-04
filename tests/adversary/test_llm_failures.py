"""Adversary tests for sentiment analysis failure cases (T042)."""

from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.sentiment import SentimentService


class TestLLMBackendFailures:
    """Adversary tests for LLM sentiment backend failure scenarios."""

    def test_llm_backend_without_api_key_raises_error(self) -> None:
        """LLM backend selected but ANTHROPIC_API_KEY missing gives clear error."""
        service = SentimentService(backend="llm")
        comments = [{"comment_id": "c0", "text": "Test"}]

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="sentiment-backend local"):
                service.analyze_batch(comments)

    def test_local_backend_without_transformers_raises_error(self) -> None:
        """Local backend selected but transformers unavailable gives clear error."""
        with patch(
            "tube_scout.services.sentiment._load_local_pipeline",
            side_effect=ImportError("No module named 'transformers'"),
        ):
            service = SentimentService(backend="local")
            comments = [{"comment_id": "c0", "text": "Test"}]

            with pytest.raises(ValueError, match="transformers"):
                service.analyze_batch(comments)

    def test_llm_malformed_response_retry_and_handle(self) -> None:
        """LLM returns malformed response: retry then handle gracefully."""
        mock_adapter = MagicMock()

        # First call returns malformed, second call raises ValueError from complete_json
        mock_adapter.complete_json.side_effect = ValueError(
            "Failed to parse LLM response as SentimentBatchResult after 2 attempts"
        )

        service = SentimentService(backend="llm")
        service._llm_adapter = mock_adapter
        comments = [{"comment_id": "c0", "text": "Test"}]

        with pytest.raises(ValueError, match="Failed to parse"):
            service.analyze_batch(comments)

    def test_empty_comments_no_error(self) -> None:
        """Comments disabled (empty comment list) returns empty, no error."""
        service = SentimentService(backend="llm")
        results = service.analyze_batch([])
        assert results == []

        service_local = SentimentService(backend="local")
        results_local = service_local.analyze_batch([])
        assert results_local == []

    def test_invalid_backend_raises_error(self) -> None:
        """Invalid backend name raises clear error."""
        with pytest.raises(ValueError, match="Unsupported sentiment backend"):
            service = SentimentService(backend="invalid")
            service.analyze_batch([{"comment_id": "c0", "text": "Test"}])
