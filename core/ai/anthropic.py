"""Anthropic provider placeholder. Not implemented; fails closed."""

from core.ai.provider import LLMProvider, ProviderUnavailable, StructuredResult, T


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = ""):
        self.model = model or "unimplemented"

    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[T], max_output_tokens: int = 1024,
    ) -> StructuredResult[T]:
        raise ProviderUnavailable("The Anthropic provider is not implemented yet")
