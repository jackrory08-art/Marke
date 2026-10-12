"""Builders shared by AI / cross-platform tests."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from core.ai.provider import (
    LLMProvider, ProviderBadOutput, ProviderError, StructuredResult, Usage,
)
from core.cross_platform_arb import MarketPair
from core.market_ref import ComparableMarket
from polymarket_client.models import OrderBook, OrderBookSide, PriceLevel, TokenOrderBook, TokenType


def future_iso(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def make_ref(platform="polymarket", market_id="1", title="Will Bitcoin close above $100k on Dec 31?",
             rules="Resolves YES if BTC closes above $100,000 on Dec 31.", end_date=None,
             outcome="Yes / No", source="Coinbase", **kw) -> ComparableMarket:
    return ComparableMarket(
        platform=platform, market_id=market_id, title=title, rules_text=rules,
        end_date=end_date if end_date is not None else "2026-12-31T00:00:00+00:00",
        outcome_label=outcome, resolution_source=source, **kw)


def make_pair(ref_a: Optional[ComparableMarket] = None, ref_b: Optional[ComparableMarket] = None,
              similarity: float = 0.8) -> MarketPair:
    ref_a = ref_a or make_ref("polymarket", "1")
    ref_b = ref_b or make_ref("kalshi", "KXBTC-100K", title="Bitcoin above $100,000 on Dec 31?")
    return MarketPair.from_refs(ref_a, ref_b, similarity, "crypto")


def make_book(yes_bid, yes_ask, no_bid=None, no_ask=None, size=100.0, market_id="m") -> OrderBook:
    """Two-sided book. NO prices default to the complement of YES."""
    no_bid = (1 - yes_ask) if no_bid is None else no_bid
    no_ask = (1 - yes_bid) if no_ask is None else no_ask

    def tob(token, bid, ask):
        t = TokenOrderBook(token)
        if bid is not None:
            t.bids = OrderBookSide([PriceLevel(bid, size)])
        if ask is not None:
            t.asks = OrderBookSide([PriceLevel(ask, size)])
        return t
    return OrderBook(market_id=market_id, yes=tob(TokenType.YES, yes_bid, yes_ask),
                     no=tob(TokenType.NO, no_bid, no_ask))


def verdict_json(verdict="identical", confidence=0.95, differences=None, short="ok") -> dict:
    return {"verdict": verdict, "confidence": confidence,
            "differences": differences or [], "short_reason": short}


class FakeProvider(LLMProvider):
    """Scripted provider. ``script`` items: a dict (-> schema), or an Exception to raise.

    The last item repeats when the script runs out.
    """
    name = "fake"
    model = "fake-1"

    def __init__(self, script=None, delay: float = 0.0, usage=Usage(100, 20)):
        self.script = list(script or [verdict_json()])
        self.calls = 0
        self.delay = delay
        self.usage = usage
        self.prompts: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def generate_structured(self, *, system, prompt, schema, max_output_tokens=1024):
        import asyncio
        self.calls += 1
        self.prompts.append((system, prompt))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            item = self.script[min(self.calls - 1, len(self.script) - 1)]
            if isinstance(item, Exception):
                raise item
            try:
                return StructuredResult(schema.model_validate(item), self.usage)
            except Exception as e:
                raise ProviderBadOutput(str(e)) from e
        finally:
            self.in_flight -= 1
