"""Wires provider, runner, verifier and queue together."""

from dataclasses import dataclass
from typing import Callable, Optional

from app.clock import utcnow
from core.ai.factory import build_provider
from core.ai.provider import LLMProvider
from core.ai.queue import VerificationQueue
from core.ai.runner import AIRunner
from core.ai.verifier import MatchVerifier
from core.pair_store import PairStore


@dataclass
class AIServices:
    config: object
    provider: LLMProvider
    runner: AIRunner
    verifier: MatchVerifier
    queue: VerificationQueue
    analyst: Optional[object] = None

    async def on_enabled_changed(self, enabled: bool, scanner=None) -> None:
        """Kill switch: AI off makes every pair unverified (never actionable);
        AI on sends them back through verification (cached verdicts are free)."""
        store = self.queue.store
        if not enabled:
            for pair in store.all():
                store.set_verification(pair.pair_id, "unverified", {
                    "status": "unverified", "reason": "ai_disabled", "verdict": None,
                    "confidence": None, "differences": [], "short_reason": "", "cached": False})
                if scanner is not None:
                    await scanner.on_pair_verified(pair)
            return
        for pair in store.all():
            if pair.verification_status == "unverified":
                store.set_verification(pair.pair_id, "pending", {})
        self.queue.enqueue_pending()

    def status(self) -> dict:
        return {
            "enabled": bool(self.config.enabled),
            "provider": self.provider.name,
            "model": self.provider.model,
            "mock": self.provider.name == "mock",
        }


def build_ai_services(
    config, db, store: PairStore, emit: Callable[[str, dict], None], *,
    provider: Optional[LLMProvider] = None, clock=utcnow, on_verified=None, **runner_kwargs,
) -> AIServices:
    """``config`` is the :class:`AIConfig` (shared by reference, so runtime changes apply)."""
    provider = provider or build_provider(config)
    runner = AIRunner(provider, db, config, clock=clock,
                      on_budget=lambda status: emit("ai_budget", status), **runner_kwargs)
    verifier = MatchVerifier(runner, db, config, clock=clock)
    queue = VerificationQueue(verifier, store, emit, workers=config.max_concurrency,
                              on_verified=on_verified)
    return AIServices(config, provider, runner, verifier, queue)
