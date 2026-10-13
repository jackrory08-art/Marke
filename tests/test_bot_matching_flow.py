"""The bot's matching hand-off and on-demand order books (no network)."""

from types import SimpleNamespace

import pytest

import run_with_dashboard as runner
from core.cross_platform_arb import MarketMatcher
from kalshi_client.models import KalshiMarket
from polymarket_client.models import Market, OrderBook
from tests.helpers import make_book
from utils.config_loader import get_default_config

NAMES = ["Zelenskyy", "Macron", "Lula", "Albanese", "Modi"]


@pytest.fixture
def bot():
    b = runner.TradingBotWithDashboard(get_default_config())
    b._running = True
    b.market_matcher = MarketMatcher(min_similarity=0.6)
    b.ai = SimpleNamespace(queue=SimpleNamespace(calls=0))
    b.ai.queue.enqueue_pending = lambda: setattr(b.ai.queue, "calls", b.ai.queue.calls + 1) or 0
    saved = dict(runner.dashboard_state.cross_platform)
    yield b
    runner.dashboard_state.cross_platform.clear()
    runner.dashboard_state.cross_platform.update(saved)


async def test_pairs_reach_the_store_and_verification_queue_after_matching(bot):
    poly = [Market(market_id=f"p{i}", condition_id=f"c{i}", yes_token_id=f"y{i}", no_token_id=f"n{i}",
                   question=f"Will {n} win the presidential election in 2028?")
            for i, n in enumerate(NAMES)]
    bot._kalshi_markets = [
        KalshiMarket(ticker=f"KXPRES-{i}", event_ticker="KXPRES", series_ticker="KXPRES",
                     title=f"Will {n} win the presidential election in 2028?", status="open")
        for i, n in enumerate(NAMES)]
    await bot._run_matching_background(poly)

    cp = runner.dashboard_state.cross_platform
    assert cp["matching_status"] == "complete" and cp["matching_progress"] == 100
    assert cp["matching_total"] == len(NAMES)             # counted in markets, not comparisons
    assert cp["matched_pairs"] == len(NAMES)
    assert len(bot.pair_store.all()) == len(NAMES)
    assert bot.ai.queue.calls >= 1, "new pairs must be queued for verification"


def test_flush_pairs_only_queues_new_ones(bot):
    from core.pair_store import PairInbox
    from tests.helpers import make_pair
    inbox, pair = PairInbox(), make_pair()
    inbox.put(pair)
    assert bot._flush_pairs(inbox) == 1 and bot.ai.queue.calls == 1
    inbox.put(pair)
    assert bot._flush_pairs(inbox) == 0 and bot.ai.queue.calls == 1
    assert bot._flush_pairs(inbox) == 0


async def test_polymarket_book_is_fetched_on_demand_when_the_stream_has_not_reached_it(bot):
    fetched = []
    on_demand = make_book(0.40, 0.42, market_id="p1")

    async def get_orderbook(market_id):
        fetched.append(market_id)
        return on_demand
    bot.client = SimpleNamespace(get_orderbook=get_orderbook)

    # 1) the live stream has no state for this market yet
    bot.data_feed = SimpleNamespace(get_market_state=lambda _id: None)
    assert await bot._fetch_polymarket_book("p1") is on_demand and fetched == ["p1"]

    # 2) the stream has an empty book (no bids/asks yet)
    empty = SimpleNamespace(order_book=OrderBook(market_id="p1"))
    bot.data_feed = SimpleNamespace(get_market_state=lambda _id: empty)
    assert await bot._fetch_polymarket_book("p1") is on_demand and len(fetched) == 2

    # 3) a usable streamed book is used as is, with no extra request
    live = SimpleNamespace(order_book=make_book(0.50, 0.52))
    bot.data_feed = SimpleNamespace(get_market_state=lambda _id: live)
    assert await bot._fetch_polymarket_book("p1") is live.order_book and len(fetched) == 2


async def test_book_fetch_failure_does_not_crash_the_scan(bot):
    async def boom(_id):
        raise RuntimeError("clob down")
    bot.client = SimpleNamespace(get_orderbook=boom)
    bot.data_feed = SimpleNamespace(get_market_state=lambda _id: None)
    assert await bot._fetch_polymarket_book("p1") is None
