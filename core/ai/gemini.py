"""Gemini provider (google-genai SDK, imported lazily)."""

import asyncio
import logging
import os
from typing import Any, Optional

from core.ai.provider import (
    LLMProvider, ProviderBadOutput, ProviderError, ProviderRateLimited,
    ProviderTransient, ProviderUnavailable, StructuredResult, T, Usage,
)

logger = logging.getLogger(__name__)

API_KEY_ENV = "GEMINI_API_KEY"
CALL_TIMEOUT_S = 60.0


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        model: str = "gemini-3.1-flash-lite",
        temperature: Optional[float] = None,
        thinking_level: str = "low",
        client: Any = None,
    ):
        self.model = model
        self.temperature = temperature
        self.thinking_level = (thinking_level or "").lower()
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        key = os.environ.get(API_KEY_ENV)
        if not key:
            raise ProviderUnavailable(f"{API_KEY_ENV} is not set")
        try:
            from google import genai
        except ImportError as e:
            raise ProviderUnavailable("google-genai is not installed") from e
        self._client = genai.Client(api_key=key)
        return self._client

    def _build_config(self, system: str, schema: type[T], max_output_tokens: int):
        try:
            from google.genai import types
        except ImportError as e:
            raise ProviderUnavailable("google-genai is not installed") from e
        kwargs: dict[str, Any] = dict(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=max_output_tokens,
        )
        if self.temperature is not None:  # unset = Google's default
            kwargs["temperature"] = self.temperature
        # thinking_level is a Gemini 3 feature
        if self.model.startswith("gemini-3") and self.thinking_level in (
            "minimal", "low", "medium", "high",
        ):
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self.thinking_level.upper()))
        return types.GenerateContentConfig(**kwargs)

    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[T], max_output_tokens: int = 1024,
    ) -> StructuredResult[T]:
        client = self._get_client()
        config = self._build_config(system, schema, max_output_tokens)
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.model, contents=prompt, config=config),
                timeout=CALL_TIMEOUT_S)
        except asyncio.TimeoutError as e:
            raise ProviderTransient("Gemini request timed out") from e
        except ProviderError:
            raise
        except Exception as e:
            raise self._classify(e) from e

        usage = _usage_of(response)
        text = getattr(response, "text", None)
        if not text:
            raise ProviderBadOutput("Empty response from model", usage)
        try:
            value = schema.model_validate_json(text)
        except Exception as e:
            raise ProviderBadOutput(f"Output failed schema validation: {e}", usage) from e
        return StructuredResult(value=value, usage=usage)

    @staticmethod
    def _classify(exc: Exception) -> ProviderError:
        code = getattr(exc, "code", None)
        if code == 429:
            return ProviderRateLimited(f"Gemini rate limited: {exc}")
        if isinstance(code, int) and code >= 500:
            return ProviderTransient(f"Gemini server error {code}")
        if isinstance(code, int):
            return ProviderError(f"Gemini API error {code}")
        # Network-level failures (httpx, connection resets) are worth retrying.
        name = type(exc).__name__
        if any(t in name for t in ("Timeout", "Connect", "Network", "Read", "Remote")):
            return ProviderTransient(f"Gemini network error: {name}")
        return ProviderError(f"Gemini call failed: {name}")


def _usage_of(response: Any) -> Usage:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return Usage()
    prompt = getattr(meta, "prompt_token_count", 0) or 0
    out = (getattr(meta, "candidates_token_count", 0) or 0) + \
          (getattr(meta, "thoughts_token_count", 0) or 0)
    return Usage(int(prompt), int(out))
