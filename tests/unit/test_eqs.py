"""Tests for EQSService."""

from unittest.mock import patch

from tube_scout.services.eqs import EQSService


class TestEQSService:
    """Tests for EQSService (T061)."""

    def test_evaluate_returns_5_axis_scores(self) -> None:
        service = EQSService()
        mock_result = {
            "relevance": 0.8,
            "accuracy": 0.9,
            "clarity": 0.7,
            "engagement": 0.6,
            "depth": 0.85,
        }
        with patch.object(service, "_call_llm", return_value=mock_result):
            result = service.evaluate(
                video_id="vid001",
                transcript_text="Lecture content...",
                retention_data=[],
                comment_data=[],
            )
        assert "relevance" in result
        assert "accuracy" in result
        assert "clarity" in result
        assert "engagement" in result
        assert "depth" in result
        assert "overall" in result
        assert 0.0 <= result["overall"] <= 1.0

    def test_evaluate_empty_input(self) -> None:
        service = EQSService()
        result = service.evaluate(
            video_id="vid001",
            transcript_text="",
            retention_data=[],
            comment_data=[],
        )
        assert result["overall"] == 0.0
