import json
from types import SimpleNamespace

import pytest

pytest.importorskip("google.genai")
from google.genai import errors, types  # noqa: E402

from core.ai.gemini import GeminiProvider  # noqa: E402
from core.ai.provider import (  # noqa: E402
    ProviderBadOutput, ProviderError, ProviderRateLimited, ProviderTransient, ProviderUnavailable,
)
from core.ai.schemas import MatchVerdict  # noqa: E402


class FakeModels:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []

    async def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        if self.exc:
            raise self.exc
        return SimpleNamespace(
            text=self.text,
            usage_metadata=SimpleNamespace(
                prompt_token_count=120, candidates_token_count=30, thoughts_token_count=10))


def client_with(models):
    return SimpleNamespace(aio=SimpleNamespace(models=models))


GOOD = json.dumps({"verdict": "identical", "confidence": 0.9, "differences": [],
                   "short_reason": "same"})


async def call(provider):
    return await provider.generate_structured(system="sys", prompt="p", schema=MatchVerdict)


async def test_config_carries_schema_and_json_mime_type():
    models = FakeModels(GOOD)
    result = await call(GeminiProvider(client=client_with(models)))
    cfg = models.calls[0].config
    assert models.calls[0].model == "gemini-3.1-flash-lite"
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema is not None
    assert cfg.system_instruction == "sys"
    assert result.value.verdict == "identical"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (120, 40)


async def test_temperature_omitted_when_unset():
    models = FakeModels(GOOD)
    await call(GeminiProvider(client=client_with(models)))
    assert models.calls[0].config.temperature is None


async def test_temperature_passed_when_set():
    models = FakeModels(GOOD)
    await call(GeminiProvider(temperature=0.4, client=client_with(models)))
    assert models.calls[0].config.temperature == 0.4


async def test_low_thinking_level_for_gemini_3_only():
    models = FakeModels(GOOD)
    await call(GeminiProvider(client=client_with(models)))
    assert models.calls[0].config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    models = FakeModels(GOOD)
    await call(GeminiProvider(model="gemini-2.5-flash-lite", client=client_with(models)))
    assert models.calls[0].config.thinking_config is None


async def test_malformed_json_raises_bad_output():
    with pytest.raises(ProviderBadOutput):
        await call(GeminiProvider(client=client_with(FakeModels("{not json"))))


async def test_schema_violation_raises_bad_output():
    bad = json.dumps({"verdict": "maybe", "confidence": 0.5, "differences": [], "short_reason": ""})
    with pytest.raises(ProviderBadOutput):
        await call(GeminiProvider(client=client_with(FakeModels(bad))))


async def test_empty_response_raises_bad_output():
    with pytest.raises(ProviderBadOutput):
        await call(GeminiProvider(client=client_with(FakeModels(""))))


async def test_missing_key_raises_unavailable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable):
        await call(GeminiProvider())


async def test_error_classification():
    rate = errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    server = errors.ServerError(503, {"error": {"message": "down", "status": "UNAVAILABLE"}})
    client = errors.ClientError(400, {"error": {"message": "bad", "status": "INVALID_ARGUMENT"}})
    with pytest.raises(ProviderRateLimited):
        await call(GeminiProvider(client=client_with(FakeModels(exc=rate))))
    with pytest.raises(ProviderTransient):
        await call(GeminiProvider(client=client_with(FakeModels(exc=server))))
    with pytest.raises(ProviderError) as e:
        await call(GeminiProvider(client=client_with(FakeModels(exc=client))))
    assert not isinstance(e.value, ProviderTransient)


def test_schema_trims_long_fields_instead_of_failing():
    v = MatchVerdict.model_validate({
        "verdict": "different", "confidence": 7, "short_reason": "x" * 1000,
        "differences": [{"kind": "other", "detail": "d" * 900}] * 12})
    assert len(v.short_reason) == 280 and v.confidence == 1.0
    assert len(v.differences) == 8 and len(v.differences[0].detail) == 300
