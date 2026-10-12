"""Provider-neutral interface for structured LLM calls."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StructuredResult(Generic[T]):
    value: T
    usage: Usage


class ProviderError(Exception):
    """Base class for provider failures."""


class ProviderUnavailable(ProviderError):
    """No API key, SDK not installed, or provider not implemented."""


class ProviderTransient(ProviderError):
    """Worth retrying: rate limit, 5xx, timeout."""


class ProviderRateLimited(ProviderTransient):
    """HTTP 429 / quota exhausted."""


class ProviderBadOutput(ProviderError):
    """The model answered, but not with valid output for the schema."""

    def __init__(self, message: str, usage: Optional[Usage] = None):
        super().__init__(message)
        self.usage = usage or Usage()


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[T], max_output_tokens: int = 1024,
    ) -> StructuredResult[T]:
        """Return the model's answer validated against ``schema``."""
