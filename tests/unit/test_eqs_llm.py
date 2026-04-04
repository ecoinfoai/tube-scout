"""Tests for EQS LLM evaluation (T064, T065-T067)."""

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from tube_scout.services.eqs import EQSService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_adapter_mock(scores: dict[str, float]) -> MagicMock:
    """Create a mock LLMAdapter returning RACED scores.

    Args:
        scores: Dict with relevance, accuracy, clarity, engagement, depth.

    Returns:
        Mocked LLMAdapter instance.
    """
    adapter = MagicMock()

    def _complete_json(
        system_prompt: str, user_prompt: str, schema: type[BaseModel],
    ) -> BaseModel:
        return schema.model_validate(scores)

    adapter.complete_json.side_effect = _complete_json
    return adapter


SAMPLE_SCORES = {
    "relevance": 0.85,
    "accuracy": 0.90,
    "clarity": 0.75,
    "engagement": 0.60,
    "depth": 0.80,
}

SAMPLE_RETENTION = [
    {"elapsed_ratio": 0.3, "audience_watch_ratio": 1.2},
    {"elapsed_ratio": 0.7, "audience_watch_ratio": 0.6},
]

SAMPLE_COMMENTS = [
    {"text": "Great explanation!", "sentiment": "positive"},
    {"text": "Too fast in the middle", "sentiment": "negative"},
]


# ===========================================================================
# T064 — Unit tests for EQS LLM evaluation
# ===========================================================================

class TestEQSLLMEvaluation:
    """T064: EQS LLM-based RACED 5-axis evaluation."""

    def test_evaluate_returns_all_5_axes(self) -> None:
        """Evaluate returns all 5 RACED axes plus overall."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        result = service.evaluate(
            video_id="vid001",
            transcript_text="Lecture content here...",
            retention_data=SAMPLE_RETENTION,
            comment_data=SAMPLE_COMMENTS,
        )

        assert result["video_id"] == "vid001"
        for axis in ("relevance", "accuracy", "clarity", "engagement", "depth"):
            assert axis in result
            assert result[axis] == SAMPLE_SCORES[axis]
        assert "overall" in result

    def test_evaluate_overall_is_mean_of_axes(self) -> None:
        """Overall score is the mean of the 5 axis scores."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        result = service.evaluate(
            video_id="vid001",
            transcript_text="Content...",
            retention_data=[],
            comment_data=[],
        )

        expected = sum(SAMPLE_SCORES.values()) / 5
        assert abs(result["overall"] - expected) < 1e-9

    def test_all_scores_bounded_0_to_1(self) -> None:
        """All axis scores must be in [0.0, 1.0]."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        result = service.evaluate(
            video_id="vid001",
            transcript_text="Content...",
            retention_data=[],
            comment_data=[],
        )

        for axis in ("relevance", "accuracy", "clarity",
                      "engagement", "depth", "overall"):
            assert 0.0 <= result[axis] <= 1.0

    def test_empty_transcript_returns_zeros(self) -> None:
        """Empty transcript returns all-zero scores without calling LLM."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        result = service.evaluate(
            video_id="vid001",
            transcript_text="",
            retention_data=[],
            comment_data=[],
        )

        assert result["overall"] == 0.0
        for axis in ("relevance", "accuracy", "clarity",
                      "engagement", "depth"):
            assert result[axis] == 0.0
        adapter.complete_json.assert_not_called()

    def test_whitespace_transcript_returns_zeros(self) -> None:
        """Whitespace-only transcript returns all-zero scores."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        result = service.evaluate(
            video_id="vid001",
            transcript_text="   \n\t  ",
            retention_data=[],
            comment_data=[],
        )

        assert result["overall"] == 0.0
        adapter.complete_json.assert_not_called()

    def test_llm_receives_retention_and_comment_context(self) -> None:
        """LLM prompt includes retention and comment data."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        service.evaluate(
            video_id="vid001",
            transcript_text="Content...",
            retention_data=SAMPLE_RETENTION,
            comment_data=SAMPLE_COMMENTS,
        )

        adapter.complete_json.assert_called_once()
        call_args = adapter.complete_json.call_args
        user_prompt = call_args[0][1] if call_args[0] else call_args[1]["user_prompt"]
        # Prompt should mention retention and comment data
        assert "retention" in user_prompt.lower() or "watch" in user_prompt.lower()
        assert "comment" in user_prompt.lower() or "feedback" in user_prompt.lower()


# ===========================================================================
# T066 — Consistency and normalization
# ===========================================================================

class TestEQSConsistency:
    """T066: Scores comparable across videos."""

    def test_consistent_prompt_structure(self) -> None:
        """System prompt is deterministic across calls."""
        adapter = _make_llm_adapter_mock(SAMPLE_SCORES)
        service = EQSService(llm=adapter)

        service.evaluate("vid001", "Content A", [], [])
        call1_system = adapter.complete_json.call_args[0][0]

        adapter.reset_mock()
        adapter.complete_json.side_effect = (
            lambda s, u, schema: schema.model_validate(SAMPLE_SCORES)
        )

        service.evaluate("vid002", "Content B", [], [])
        call2_system = adapter.complete_json.call_args[0][0]

        assert call1_system == call2_system

    def test_scores_normalized_to_0_1(self) -> None:
        """Edge-case scores at boundaries are valid."""
        edge_scores = {
            "relevance": 0.0,
            "accuracy": 1.0,
            "clarity": 0.5,
            "engagement": 0.0,
            "depth": 1.0,
        }
        adapter = _make_llm_adapter_mock(edge_scores)
        service = EQSService(llm=adapter)

        result = service.evaluate("vid001", "Content...", [], [])

        for axis in ("relevance", "accuracy", "clarity",
                      "engagement", "depth"):
            assert 0.0 <= result[axis] <= 1.0


# ===========================================================================
# T067 — Malformed LLM response handling
# ===========================================================================

class TestEQSMalformedResponse:
    """T067: Handling malformed LLM responses."""

    def test_llm_value_error_propagates(self) -> None:
        """ValueError from LLMAdapter propagates to caller."""
        adapter = MagicMock()
        adapter.complete_json.side_effect = ValueError(
            "Failed to parse LLM response"
        )
        service = EQSService(llm=adapter)

        with pytest.raises(ValueError, match="Failed to parse"):
            service.evaluate("vid001", "Content...", [], [])

    def test_no_llm_configured_raises_not_implemented(self) -> None:
        """Without LLM adapter, evaluate raises NotImplementedError."""
        service = EQSService()

        with pytest.raises(NotImplementedError, match="LLM backend"):
            service.evaluate("vid001", "Content...", [], [])

    def test_connection_error_propagates(self) -> None:
        """ConnectionError from LLM propagates."""
        adapter = MagicMock()
        adapter.complete_json.side_effect = ConnectionError("unreachable")
        service = EQSService(llm=adapter)

        with pytest.raises(ConnectionError):
            service.evaluate("vid001", "Content...", [], [])
