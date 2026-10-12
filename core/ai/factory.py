"""Build the configured provider."""

from core.ai.provider import LLMProvider


def build_provider(ai_config) -> LLMProvider:
    name = ai_config.provider.lower()
    if name == "gemini":
        from core.ai.gemini import GeminiProvider
        return GeminiProvider(
            model=ai_config.model, temperature=ai_config.temperature,
            thinking_level=ai_config.thinking_level)
    if name == "anthropic":
        from core.ai.anthropic import AnthropicProvider
        return AnthropicProvider(model=ai_config.model)
    if name == "mock":
        from core.ai.mock import MockProvider
        return MockProvider()
    raise ValueError(f"Unknown AI provider: {ai_config.provider}")
