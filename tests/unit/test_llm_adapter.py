"""Tests for LLMAdapter."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from tube_scout.services.llm_adapter import LLMAdapter


class SampleSchema(BaseModel):
    """Sample Pydantic model for testing complete_json."""

    name: str
    score: float


class TestLLMAdapterInit:
    """Tests for LLMAdapter initialization and validation."""

    def test_unsupported_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported provider"):
            LLMAdapter(provider="gemini")

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_anthropic_api_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            LLMAdapter(provider="claude")

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_openai_api_key_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            LLMAdapter(provider="openai")

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_claude_provider_default_model(self) -> None:
        adapter = LLMAdapter(provider="claude")
        assert adapter.provider == "claude"
        assert adapter.model == "claude-sonnet-4-20250514"

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_openai_provider_default_model(self) -> None:
        adapter = LLMAdapter(provider="openai")
        assert adapter.provider == "openai"
        assert adapter.model == "gpt-4o"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_custom_model_override(self) -> None:
        adapter = LLMAdapter(provider="claude", model="claude-opus-4-20250514")
        assert adapter.model == "claude-opus-4-20250514"

    @patch.dict(
        "os.environ",
        {"TUBE_SCOUT_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test"},
    )
    def test_env_var_provider_selection(self) -> None:
        adapter = LLMAdapter()
        assert adapter.provider == "openai"

    @patch.dict(
        "os.environ",
        {
            "TUBE_SCOUT_LLM_PROVIDER": "openai",
            "ANTHROPIC_API_KEY": "sk-test",
        },
    )
    def test_constructor_param_overrides_env_var(self) -> None:
        adapter = LLMAdapter(provider="claude")
        assert adapter.provider == "claude"


class TestLLMAdapterComplete:
    """Tests for LLMAdapter.complete() method."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_claude_returns_text(self) -> None:
        adapter = LLMAdapter(provider="claude")
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hello from Claude")]
        adapter._client.messages.create = MagicMock(return_value=mock_response)

        result = adapter.complete("You are a helper.", "Say hello.")
        assert result == "Hello from Claude"
        adapter._client.messages.create.assert_called_once()

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_complete_openai_returns_text(self) -> None:
        adapter = LLMAdapter(provider="openai")
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello from GPT"))]
        adapter._client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        result = adapter.complete("You are a helper.", "Say hello.")
        assert result == "Hello from GPT"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_connection_error_propagation(self) -> None:
        adapter = LLMAdapter(provider="claude")
        adapter._client.messages.create = MagicMock(
            side_effect=ConnectionError("Service unreachable")
        )

        with pytest.raises(ConnectionError, match="Service unreachable"):
            adapter.complete("system", "user")

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_runtime_error_on_api_error(self) -> None:
        adapter = LLMAdapter(provider="claude")
        adapter._client.messages.create = MagicMock(
            side_effect=RuntimeError("API error")
        )

        with pytest.raises(RuntimeError, match="API error"):
            adapter.complete("system", "user")


class TestLLMAdapterCompleteJson:
    """Tests for LLMAdapter.complete_json() method."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_json_returns_validated_model(self) -> None:
        adapter = LLMAdapter(provider="claude")
        valid_json = json.dumps({"name": "test", "score": 0.95})
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=valid_json)]
        adapter._client.messages.create = MagicMock(return_value=mock_response)

        result = adapter.complete_json("Return JSON.", "Give me data.", SampleSchema)
        assert isinstance(result, SampleSchema)
        assert result.name == "test"
        assert result.score == 0.95

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_json_retry_on_malformed_json(self) -> None:
        adapter = LLMAdapter(provider="claude")
        malformed = "not json at all"
        valid_json = json.dumps({"name": "retry", "score": 0.5})

        mock_bad = MagicMock()
        mock_bad.content = [MagicMock(text=malformed)]
        mock_good = MagicMock()
        mock_good.content = [MagicMock(text=valid_json)]

        adapter._client.messages.create = MagicMock(
            side_effect=[mock_bad, mock_good]
        )

        result = adapter.complete_json("Return JSON.", "Give me data.", SampleSchema)
        assert isinstance(result, SampleSchema)
        assert result.name == "retry"
        assert adapter._client.messages.create.call_count == 2

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_json_raises_after_retry_failure(self) -> None:
        adapter = LLMAdapter(provider="claude")
        malformed = "not json"

        mock_bad = MagicMock()
        mock_bad.content = [MagicMock(text=malformed)]

        adapter._client.messages.create = MagicMock(
            return_value=mock_bad
        )

        with pytest.raises(ValueError, match="Failed to parse"):
            adapter.complete_json("Return JSON.", "Give me data.", SampleSchema)

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_json_connection_error(self) -> None:
        adapter = LLMAdapter(provider="claude")
        adapter._client.messages.create = MagicMock(
            side_effect=ConnectionError("unreachable")
        )

        with pytest.raises(ConnectionError):
            adapter.complete_json("Return JSON.", "Give me data.", SampleSchema)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_complete_json_openai_returns_validated_model(self) -> None:
        adapter = LLMAdapter(provider="openai")
        valid_json = json.dumps({"name": "openai_test", "score": 0.8})
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content=valid_json))
        ]
        adapter._client.chat.completions.create = MagicMock(
            return_value=mock_response
        )

        result = adapter.complete_json("Return JSON.", "Give me data.", SampleSchema)
        assert isinstance(result, SampleSchema)
        assert result.name == "openai_test"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"})
    def test_complete_json_extracts_json_from_markdown_block(self) -> None:
        adapter = LLMAdapter(provider="claude")
        wrapped = '```json\n{"name": "wrapped", "score": 0.7}\n```'
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=wrapped)]
        adapter._client.messages.create = MagicMock(return_value=mock_response)

        result = adapter.complete_json("Return JSON.", "Give me data.", SampleSchema)
        assert isinstance(result, SampleSchema)
        assert result.name == "wrapped"
