"""Provider-agnostic LLM adapter supporting Claude and GPT-4o."""

import json
import os
import re
from typing import Any

from pydantic import BaseModel

from tube_scout.models.config import DEFAULT_API_TIMEOUT_SECONDS

LLM_MAX_TOKENS = 4096
LLM_MAX_RETRIES = 2

_SUPPORTED_PROVIDERS = {"claude", "openai"}

_DEFAULT_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

_API_KEY_ENV_VARS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class LLMAdapter:
    """Provider-agnostic LLM adapter supporting Claude (default) and GPT-4o."""

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        """Initialize with provider selection.

        Args:
            provider: LLM provider ("claude" or "openai"). If None, reads
                from TUBE_SCOUT_LLM_PROVIDER env var (default "claude").
            model: Model name override. Defaults to provider's best model.

        Raises:
            ValueError: If provider is not supported.
            ValueError: If required API key env var is missing.
        """
        if provider is None:
            provider = os.environ.get("TUBE_SCOUT_LLM_PROVIDER", "claude")

        if provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider: '{provider}'. "
                f"Supported: {sorted(_SUPPORTED_PROVIDERS)}"
            )

        self.provider: str = provider
        self.model: str = model or _DEFAULT_MODELS[provider]

        api_key_var = _API_KEY_ENV_VARS[provider]
        api_key = os.environ.get(api_key_var)
        if not api_key:
            raise ValueError(f"Missing required environment variable: {api_key_var}")

        self._client: Any = self._build_client(provider, api_key)

    def _build_client(self, provider: str, api_key: str) -> Any:
        """Build the provider-specific API client.

        Args:
            provider: LLM provider name.
            api_key: API key for the provider.

        Returns:
            Provider API client instance.
        """
        if provider == "claude":
            import anthropic

            return anthropic.Anthropic(
                api_key=api_key, timeout=DEFAULT_API_TIMEOUT_SECONDS
            )
        else:
            import openai

            return openai.OpenAI(api_key=api_key, timeout=DEFAULT_API_TIMEOUT_SECONDS)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt and get a text completion.

        Args:
            system_prompt: System/instruction prompt.
            user_prompt: User message.

        Returns:
            LLM response text.

        Raises:
            ConnectionError: If LLM service is unreachable.
            RuntimeError: If LLM returns an error response.
        """
        if self.provider == "claude":
            response = self._client.messages.create(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        else:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        """Send a structured JSON prompt validated against a schema.

        Args:
            system_prompt: System prompt instructing JSON output format.
            user_prompt: User message.
            schema: Pydantic BaseModel class to validate response against.

        Returns:
            Validated Pydantic model instance.

        Raises:
            ValueError: If response cannot be parsed as valid JSON matching schema.
            ConnectionError: If LLM service is unreachable.
        """
        last_error: str = ""
        for attempt in range(LLM_MAX_RETRIES):
            prompt = user_prompt
            if attempt > 0 and last_error:
                prompt = (
                    f"{user_prompt}\n\n"
                    f"Previous response was invalid: {last_error}\n"
                    f"Please return valid JSON matching the schema."
                )

            raw = self.complete(system_prompt, prompt)
            text = self._extract_json(raw)

            try:
                data = json.loads(text)
                return schema.model_validate(data)
            except (json.JSONDecodeError, Exception) as exc:
                last_error = str(exc)

        raise ValueError(
            f"Failed to parse LLM response as {schema.__name__} "
            f"after 2 attempts: {last_error}"
        )

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, handling markdown code blocks.

        Args:
            text: Raw LLM response text.

        Returns:
            Extracted JSON string.
        """
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()
