"""Seeded demo of cross-platform pairs for ``data_mode: simulation``.

Gives the cross-platform UI something realistic to show without network
access: synthetic Kalshi and PredictIt markets paired with Polymarket-style
ones, covering every verdict the gate can reach. Prices wobble slightly on each
fetch so the dashboard looks live. All names, rules and prices are made up.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.cross_platform_arb import MarketPair
from core.fees import UnknownSizeLevel
from core.market_ref import ComparableMarket
from polymarket_client.models import (
    OrderBook, OrderBookSide, PriceLevel, TokenOrderBook, TokenType,
)


@dataclass
class DemoSpec:
    a: ComparableMarket
    b: ComparableMarket
    similarity: float
    category: str
    yes_a: tuple   # (bid, ask) for the first market's YES
    yes_b: tuple   # (bid, ask) for the second market's YES
    size: Optional[float]   # None = size unknown (PredictIt)


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def build_specs() -> list[DemoSpec]:
    fed_rules = ("Resolves YES if the FOMC lowers the target federal funds rate range at its "
                 "March 2027 meeting. Resolution source: federalreserve.gov.")
    btc_rules_p = ("Resolves YES if the Coinbase BTC-USD daily close on December 31 is above "
                   "$100,000.")
    btc_rules_k = ("If the BTC/USD price at 5pm EST on December 31 is above $100,000 according "
                   "to CF Benchmarks, the market resolves YES.")
    return [
        DemoSpec(  # identical, real edge
            ComparableMarket("polymarket", "sim-fed", "Will the Fed cut rates at the March 2027 FOMC meeting?",
                             fed_rules, _iso(48), "Yes / No", "federalreserve.gov"),
            ComparableMarket("kalshi", "KXFEDCUT-27MAR", "Will the Fed cut rates at the March 2027 FOMC meeting?",
                             fed_rules, _iso(48), "YES = Fed lowers the range", "federalreserve.gov"),
            0.97, "finance", (0.40, 0.42), (0.55, 0.57), 180.0),
        DemoSpec(  # caveats (different date and source), edge
            ComparableMarket("polymarket", "sim-btc", "Will Bitcoin close above $100,000 on December 31?",
                             btc_rules_p, _iso(80), "Yes / No", "Coinbase"),
            ComparableMarket("kalshi", "KXBTCD-31DEC-T100000", "Will Bitcoin close above $100,000 on December 31?",
                             btc_rules_k, _iso(81), "YES = above $100,000", "CF Benchmarks"),
            0.93, "crypto", (0.61, 0.63), (0.74, 0.76), 40.0),
        DemoSpec(  # different threshold -> rejected
            ComparableMarket("polymarket", "sim-eth", "Will Ethereum trade above $5,000 by June 30?",
                             "Resolves YES if ETH trades above $5,000 on any major exchange before July 1.",
                             _iso(150), "Yes / No", "Coinbase"),
            ComparableMarket("kalshi", "KXETH-30JUN-T6000", "Will Ethereum trade above $6,000 by June 30?",
                             "Resolves YES if ETH trades above $6,000 on Coinbase before July 1.",
                             _iso(150), "YES = above $6,000", "Coinbase"),
            0.88, "crypto", (0.30, 0.33), (0.42, 0.45), 90.0),
        DemoSpec(  # inverse polarity -> rejected
            ComparableMarket("polymarket", "sim-senate", "Will the Senate pass the farm bill this year?",
                             "Resolves YES if the farm bill passes the Senate before January 1.",
                             _iso(70), "Yes / No", "congress.gov"),
            ComparableMarket("kalshi", "KXFARM-FAIL", "Will the Senate fail to pass the farm bill this year?",
                             "Resolves YES if the farm bill does not pass the Senate before January 1.",
                             _iso(70), "YES = bill does not pass", "congress.gov"),
            0.84, "politics", (0.44, 0.47), (0.50, 0.53), 120.0),
        DemoSpec(  # PredictIt, no rules text, edge -> capped at caveats, manual trade
            ComparableMarket("polymarket", "sim-dem28", "Will a Democrat win the 2028 presidential election?",
                             "Resolves YES if the winner of the 2028 US presidential election is the "
                             "Democratic Party nominee.", _iso(760), "Yes / No", "AP"),
            ComparableMarket("predictit", "7456:28001", "Will a Democrat win the 2028 presidential election? — Democratic",
                             "", _iso(760), "YES = Democratic", ""),
            0.9, "politics", (0.48, 0.50), (0.28, 0.30), None),
        DemoSpec(  # PredictIt, efficient prices
            ComparableMarket("polymarket", "sim-gop-house", "Will Republicans control the House after the 2026 midterms?",
                             "Resolves YES if Republicans hold a majority of House seats after the 2026 midterms.",
                             _iso(25), "Yes / No", "Clerk of the House"),
            ComparableMarket("predictit", "7790:30114", "Will Republicans control the House after the 2026 midterms? — Republican",
                             "", _iso(25), "YES = Republican", ""),
            0.91, "politics", (0.52, 0.54), (0.52, 0.54), None),
        DemoSpec(  # Kalshi/PredictIt
            ComparableMarket("kalshi", "KXUNRATE-27JAN-T45", "Will the US unemployment rate be above 4.5% in January 2027?",
                             "Resolves YES if the BLS reports a January 2027 unemployment rate above 4.5%.",
                             _iso(100), "YES = above 4.5%", "BLS"),
            ComparableMarket("predictit", "7822:30341", "Will the US unemployment rate be above 4.5% in January 2027? — Above 4.5%",
                             "", _iso(100), "YES = above 4.5%", ""),
            0.9, "finance", (0.28, 0.30), (0.27, 0.29), None),
        DemoSpec(  # efficient, thin
            ComparableMarket("polymarket", "sim-nba", "Will the Celtics win the NBA championship?",
                             "Resolves YES if the Boston Celtics win the NBA Finals.", _iso(200),
                             "Yes / No", "NBA"),
            ComparableMarket("kalshi", "KXNBA-CEL", "Will the Celtics win the NBA championship?",
                             "Resolves YES if the Boston Celtics win the NBA Finals.", _iso(200),
                             "YES = Celtics win", "NBA"),
            0.96, "sports", (0.18, 0.20), (0.19, 0.21), 14.0),
        DemoSpec(  # caveats, efficient
            ComparableMarket("polymarket", "sim-oscar", "Will 'The Brutalist' win Best Picture?",
                             "Resolves YES if The Brutalist wins Best Picture at the next Academy Awards.",
                             _iso(130), "Yes / No", "Academy Awards"),
            ComparableMarket("kalshi", "KXOSCARPIC-BRUT", "Will The Brutalist win the Oscar for Best Picture?",
                             "Resolves YES if The Brutalist is announced as the Best Picture winner.",
                             _iso(131), "YES = wins", "Academy Awards"),
            0.82, "entertainment", (0.10, 0.12), (0.11, 0.13), 60.0),
        DemoSpec(  # tech, efficient
            ComparableMarket("polymarket", "sim-gpt", "Will OpenAI release a new flagship model before July?",
                             "Resolves YES if OpenAI publicly releases a new flagship model before July 1.",
                             _iso(60), "Yes / No", "openai.com"),
            ComparableMarket("kalshi", "KXOAI-FLAG", "Will OpenAI release a new flagship model before July?",
                             "Resolves YES if OpenAI publicly releases a new flagship model before July 1.",
                             _iso(60), "YES = released", "openai.com"),
            0.95, "tech", (0.63, 0.65), (0.64, 0.66), 75.0),
    ]


def _book(market_id: str, bid: float, ask: float, size: Optional[float]) -> OrderBook:
    """Two-sided YES book; the NO side is the complement."""
    def level(price: float):
        return PriceLevel(price, size) if size is not None else UnknownSizeLevel(price)

    def side(*prices):
        return OrderBookSide([level(max(0.01, min(0.99, round(p, 3)))) for p in prices])
    yes = TokenOrderBook(TokenType.YES, bids=side(bid, bid - 0.02), asks=side(ask, ask + 0.02))
    no = TokenOrderBook(TokenType.NO, bids=side(1 - ask, 1 - ask - 0.02), asks=side(1 - bid, 1 - bid + 0.02))
    return OrderBook(market_id=market_id, yes=yes, no=no)


class DemoMarkets:
    """Serves wobbling order books for the demo pairs, keyed by (platform, id)."""

    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)
        self.specs = build_specs()
        self._prices: dict[tuple[str, str], tuple[tuple, Optional[float]]] = {}
        for s in self.specs:
            self._prices[(s.a.platform, s.a.market_id)] = (s.yes_a, s.size)
            self._prices[(s.b.platform, s.b.market_id)] = (s.yes_b, s.size)

    def pairs(self) -> list[MarketPair]:
        return [MarketPair.from_refs(s.a, s.b, s.similarity, s.category) for s in self.specs]

    def fetcher(self, platform: str):
        async def fetch(market_id: str) -> Optional[OrderBook]:
            entry = self._prices.get((platform, market_id))
            if entry is None:
                return None
            (bid, ask), size = entry
            wobble = self._rng.uniform(-0.004, 0.004)
            return _book(market_id, bid + wobble, ask + wobble, size)
        return fetch
