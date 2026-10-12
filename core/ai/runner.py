"""Shared plumbing for every model call: concurrency cap, rate limit, daily
budget, retries and usage accounting."""

import asyncio
import logging
import random
import time
from datetime import datetime
from typing import Callable, Optional

from app import repo
from app.clock import utcnow
from core.ai.provider import (
    LLMProvider, ProviderBadOutput, ProviderTransient, StructuredResult, T, Usage,
)

logger = logging.getLogger(__name__)


class BudgetExhausted(Exception):
    """The daily call or cost budget has been used up. No call was made."""

    def __init__(self, kind: str):
        super().__init__(f"AI daily {kind} budget exhausted")
        self.kind = kind


class RateLimiter:
    """Evenly spaced requests: at most ``rpm`` per minute."""

    def __init__(self, rpm_provider: Callable[[], int], monotonic=time.monotonic, sleep=asyncio.sleep):
        self._rpm = rpm_provider
        self._mono = monotonic
        self._sleep = sleep
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            interval = 60.0 / max(1, self._rpm())
            now = self._mono()
            wait = self._next_at - now
            self._next_at = max(now, self._next_at) + interval
        if wait > 0:
            await self._sleep(wait)


def estimate_cost(cfg, model: str, usage: Usage) -> float:
    prices = (cfg.pricing or {}).get(model)
    if not prices:
        return 0.0
    return (usage.input_tokens * prices.get("input_per_mtok", 0.0)
            + usage.output_tokens * prices.get("output_per_mtok", 0.0)) / 1_000_000


class AIRunner:
    """Runs structured calls against a provider under budget and rate limits.

    ``purpose`` is ``"verify"`` or ``"analyze"``; analysis may only use the
    share of the daily budget not reserved for verification.
    """

    def __init__(
        self, provider: LLMProvider, db, cfg, *,
        clock: Callable[[], datetime] = utcnow,
        sleep=asyncio.sleep, monotonic=time.monotonic,
        jitter: Callable[[], float] = random.random,
        on_budget: Optional[Callable[[dict], None]] = None,
    ):
        self.provider = provider
        self.db = db
        self.cfg = cfg
        self.clock = clock
        self._sleep = sleep
        self._jitter = jitter
        self.on_budget = on_budget
        self._sem = asyncio.Semaphore(max(1, cfg.max_concurrency))
        self._limiter = RateLimiter(lambda: self.cfg.requests_per_minute, monotonic, sleep)
        self._budget_lock = asyncio.Lock()
        self._inflight = 0
        self.max_in_flight_seen = 0  # observability / tests

    # -------------------------------------------------------------- budget
    def _usage_sync(self) -> dict:
        with self.db.session() as s:
            return repo.get_usage_today(s, self.clock())

    async def usage_today(self) -> dict:
        return await asyncio.to_thread(self._usage_sync)

    def _limits(self, purpose: str) -> tuple[float, float]:
        calls, cost = float(self.cfg.daily_call_budget), float(self.cfg.daily_cost_budget_usd)
        if purpose == "analyze":
            keep = 1.0 - self.cfg.verifier_reserve_pct / 100.0
            calls, cost = calls * keep, cost * keep
        return calls, cost

    async def budget_status(self) -> dict:
        usage = await self.usage_today()
        return self._status(usage)

    def _status(self, usage: dict) -> dict:
        calls_budget = self.cfg.daily_call_budget
        cost_budget = self.cfg.daily_cost_budget_usd
        exhausted = usage["calls"] >= calls_budget or (
            cost_budget > 0 and usage["cost_usd"] >= cost_budget)
        return {
            "calls_today": usage["calls"], "call_budget": calls_budget,
            "cost_today": round(usage["cost_usd"], 6), "cost_budget": cost_budget,
            "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
            "exhausted": bool(exhausted),
        }

    async def _reserve(self, purpose: str) -> None:
        async with self._budget_lock:
            usage = await self.usage_today()
            calls_limit, cost_limit = self._limits(purpose)
            if usage["calls"] + self._inflight >= calls_limit:
                self._notify(usage, exhausted=True)
                raise BudgetExhausted("call")
            if cost_limit > 0 and usage["cost_usd"] >= cost_limit:
                self._notify(usage, exhausted=True)
                raise BudgetExhausted("cost")
            self._inflight += 1
            self.max_in_flight_seen = max(self.max_in_flight_seen, self._inflight)

    def _notify(self, usage: dict, exhausted: Optional[bool] = None) -> None:
        if self.on_budget:
            status = self._status(usage)
            if exhausted:
                status["exhausted"] = True
            try:
                self.on_budget(status)
            except Exception:
                logger.debug("on_budget callback failed", exc_info=True)

    def _record_sync(self, usage: Usage, cost: float) -> dict:
        with self.db.session() as s:
            repo.record_usage(
                s, self.provider.name, self.provider.model,
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                cost_usd=cost, now=self.clock())
            return repo.get_usage_today(s, self.clock())

    async def _record(self, usage: Usage) -> float:
        cost = estimate_cost(self.cfg, self.provider.model, usage)
        totals = await asyncio.to_thread(self._record_sync, usage, cost)
        self._notify(totals)
        return cost

    # ---------------------------------------------------------------- call
    async def call(
        self, *, system: str, prompt: str, schema: type[T], purpose: str = "verify",
    ) -> tuple[StructuredResult[T], float]:
        """Return ``(result, cost_usd)``.

        Raises ``BudgetExhausted`` before any call when over budget, and the
        provider's own errors otherwise (after retrying transient ones).
        """
        attempt = 0
        while True:
            async with self._sem:
                await self._limiter.acquire()
                await self._reserve(purpose)  # budget is checked before every attempt
                try:
                    result = await self.provider.generate_structured(
                        system=system, prompt=prompt, schema=schema,
                        max_output_tokens=self.cfg.max_output_tokens)
                except ProviderTransient:
                    await self._record(Usage())
                    if attempt >= self.cfg.max_retries:
                        raise
                except ProviderBadOutput as e:
                    await self._record(e.usage)
                    raise
                except BaseException:
                    raise
                else:
                    cost = await self._record(result.usage)
                    return result, cost
                finally:
                    self._inflight -= 1
            delay = min(30.0, 2.0 ** attempt) + self._jitter() * 0.5
            logger.info("AI call failed transiently; retrying in %.1fs", delay)
            await self._sleep(delay)
            attempt += 1
