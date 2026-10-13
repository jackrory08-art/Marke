"""Matching speed/handoff, Kalshi combo-market filtering and the missing-AI-key signal."""

import asyncio
import threading

import httpx
import pytest

from core.ai.gemini import API_KEY_ENV, GeminiProvider
from core.ai.service import build_ai_services
from core.cross_platform_arb import MarketMatcher
from core.pair_store import PairInbox, PairStore
from kalshi_client.api import KalshiClient, is_multivariate
from tests.helpers import FakeProvider, make_pair, make_ref


def politics(platform, mid, who):
    return make_ref(platform, mid, title=f"Will {who} win the presidential election in 2028?")


# ------------------------------------------------------------------ matcher
async def test_indexed_matching_pairs_real_matches_and_skips_unrelated():
    names = ["Zelenskyy", "Macron", "Lula", "Albanese", "Modi", "Sunak"]
    a = [politics("polymarket", f"p{i}", n) for i, n in enumerate(names)]
    b = [politics("kalshi", f"k{i}", n) for i, n in enumerate(names)]
    # a Kalshi market about something else must not be paired with anything
    b.append(make_ref("kalshi", "k-other", title="Will the Fed raise interest rates in March?"))
    got = []
    matcher = MarketMatcher(min_similarity=0.6)
    pairs = await matcher.match_refs(a, b, on_match=got.append)
    assert len(pairs) == len(names) and got == pairs
    for pair in pairs:
        assert pair.market_a_id[1:] == pair.market_b_id[1:]       # p3 <-> k3
    assert {p.market_b_id for p in pairs}.isdisjoint({"k-other"})


async def test_matching_only_compares_markets_that_share_a_word():
    matcher = MarketMatcher(min_similarity=0.6)
    calls = []
    original = matcher.calculate_similarity
    matcher.calculate_similarity = lambda x, y: (calls.append(1), original(x, y))[1]
    a = [politics("polymarket", f"p{i}", f"Candidate{i}x") for i in range(40)]
    b = [politics("kalshi", f"k{i}", f"Candidate{i}x") for i in range(40)]
    pairs = await matcher.match_refs(a, b)
    assert len(pairs) == 40
    assert len(calls) < 40 * 40 / 4, f"{len(calls)} comparisons: the index is not pruning"


async def test_matching_reports_progress_and_finishes_at_100_percent():
    progress = []
    a = [politics("polymarket", f"p{i}", f"Person{i}z") for i in range(25)]
    b = [politics("kalshi", f"k{i}", f"Person{i}z") for i in range(25)]
    await MarketMatcher().match_refs(a, b, on_progress=lambda c, t, m: progress.append((c, t, m)))
    assert progress[-1] == (25, 25, 25)
    assert all(c <= t for c, t, _ in progress)


async def test_matching_thousands_of_markets_is_fast():
    """Used to take tens of minutes for ~700 x ~3,800; it must now be seconds."""
    import time
    a = [politics("polymarket", f"p{i}", f"Name{i}q Surname{i % 90}") for i in range(900)]
    b = [politics("kalshi", f"k{i}", f"Name{i}q Surname{i % 90}") for i in range(2500)]
    start = time.monotonic()
    pairs = await MarketMatcher().match_refs(a, b)
    assert time.monotonic() - start < 30
    assert len(pairs) > 800


async def test_sports_markets_match_across_team_name_aliases():
    """'Chiefs' and 'Kansas City' share no word, but are the same team."""
    a = [make_ref("polymarket", "p1", title="Chiefs vs. Seahawks"),
         make_ref("polymarket", "p2", title="Lakers vs. Celtics")]
    b = [make_ref("kalshi", "k1", title="Kansas City at Seattle winner?"),
         make_ref("kalshi", "k2", title="Los Angeles L at Boston winner?"),
         make_ref("kalshi", "k3", title="Will the Fed cut rates?")]
    pairs = await MarketMatcher(min_similarity=0.6).match_refs(a, b)
    assert ("p1", "k1") in {(p.market_a_id, p.market_b_id) for p in pairs}


# -------------------------------------------------------------- pair inbox
def test_pair_inbox_hands_pairs_over_in_order_across_threads():
    inbox = PairInbox()
    pairs = [make_pair(make_ref("polymarket", f"q{i}", title=f"Inbox market {i}")) for i in range(200)]
    t = threading.Thread(target=lambda: [inbox.put(p) for p in pairs])
    t.start()
    t.join()
    assert len(inbox) == 200
    drained = inbox.drain()
    assert drained == pairs and inbox.drain() == [] and len(inbox) == 0


def test_flushed_pairs_are_new_to_the_store_only_once():
    store, inbox = PairStore(), PairInbox()
    pair = make_pair()
    inbox.put(pair)
    assert store.add_many(inbox.drain()) == [pair]
    inbox.put(pair)                           # found again by a later matching run
    assert store.add_many(inbox.drain()) == []


# ------------------------------------------------------------ Kalshi combos
@pytest.mark.parametrize("market,expected", [
    ({"ticker": "KXMVESPORTSMULTIGAMEEXTENDED-S202-ABC", "title": "x"}, True),
    ({"ticker": "KXNBA-1", "event_ticker": "KXMVECROSS-1", "title": "x"}, True),
    ({"ticker": "A", "title": "yes Boston,no Dallas wins by over 4.5 points"}, True),
    ({"ticker": "A", "title": "No Jo Adell: 2+,yes Jose Ramirez: 1+"}, True),
    ({"ticker": "A", "mve_collection_ticker": "KXMVE-1", "title": "x"}, True),
    ({"ticker": "KXPRES-28-VANCE", "title": "Will JD Vance win the 2028 presidential election?"}, False),
    ({"ticker": "KXBTC-1", "title": "Bitcoin above $100,000, or higher, on Dec 31?"}, False),
    ({"ticker": "KXFED-1", "title": "Yes, the Fed will cut rates"}, False),
])
def test_is_multivariate(market, expected):
    assert is_multivariate(market) is expected


def kalshi_market(ticker, title="Real market", **kw):
    return {"ticker": ticker, "event_ticker": ticker.split("-")[0], "title": title, "status": "open", **kw}


async def test_list_markets_drops_combo_markets_and_asks_kalshi_to_exclude_them():
    client = KalshiClient()
    seen = []

    async def fake_get(endpoint, params=None):
        seen.append(dict(params or {}))
        return {"markets": [kalshi_market("KXA-1"), kalshi_market("KXMVEX-9", "yes A,yes B"),
                            kalshi_market("KXB-1")], "cursor": None}
    client._get = fake_get
    markets, _ = await client.list_markets()
    assert [m.ticker for m in markets] == ["KXA-1", "KXB-1"]
    assert seen[0].get("mve_filter") == "exclude"


async def test_list_markets_retries_without_the_filter_if_kalshi_rejects_it():
    client = KalshiClient()
    seen = []

    async def fake_get(endpoint, params=None):
        seen.append(dict(params or {}))
        if "mve_filter" in (params or {}):
            req = httpx.Request("GET", "https://x")
            raise httpx.HTTPStatusError("bad", request=req, response=httpx.Response(400, request=req))
        return {"markets": [kalshi_market("KXA-1"), kalshi_market("KXMVEX-9", "yes A,yes B")], "cursor": None}
    client._get = fake_get
    markets, _ = await client.list_markets()
    assert [m.ticker for m in markets] == ["KXA-1"]            # combo still dropped locally
    await client.list_markets()
    assert "mve_filter" not in seen[-1]                         # and not asked again


async def test_list_all_markets_keeps_paging_past_a_page_that_was_all_combos():
    client = KalshiClient()
    pages = {
        None: {"markets": [kalshi_market(f"KXMVE-{i}", "yes A,yes B") for i in range(5)], "cursor": "c1"},
        "c1": {"markets": [kalshi_market("KXREAL-1"), kalshi_market("KXREAL-2")], "cursor": None},
    }

    async def fake_get(endpoint, params=None):
        return pages[(params or {}).get("cursor")]
    client._get = fake_get
    markets = await client.list_all_markets(max_markets=100)
    assert [m.ticker for m in markets] == ["KXREAL-1", "KXREAL-2"]


# ------------------------------------------------------- missing AI key flag
def test_ai_status_reports_a_missing_gemini_key(db, ai_config, clock, monkeypatch):
    store = PairStore()
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    svc = build_ai_services(ai_config, db, store, lambda *_: None,
                            provider=GeminiProvider(), clock=clock)
    assert svc.configured() is False and svc.status()["configured"] is False
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    assert svc.configured() is True and svc.status()["configured"] is True


def test_non_gemini_providers_never_report_a_missing_key(db, ai_config, clock):
    svc = build_ai_services(ai_config, db, PairStore(), lambda *_: None,
                            provider=FakeProvider(), clock=clock)
    assert svc.status()["configured"] is True


# ------------------------------------------------------------ scan summary
async def test_last_scan_reports_how_many_pairs_had_live_prices(config, state):
    from core.cross_platform_arb import CrossPlatformArbEngine
    from core.cross_platform_scanner import CrossPlatformScanner
    from tests.helpers import make_book
    store = PairStore()
    priced, unpriced = make_pair(make_ref("polymarket", "a", title="Priced market a")), \
        make_pair(make_ref("polymarket", "b", title="Unpriced market b"))
    store.add_many([priced, unpriced])

    async def poly(market_id):
        return None if market_id == "b" else make_book(0.40, 0.42)

    async def kalshi(_):
        return make_book(0.40, 0.42)
    scanner = CrossPlatformScanner(CrossPlatformArbEngine(min_edge=0.02), store,
                                   {"polymarket": poly, "kalshi": kalshi}, state, config=config)
    await scanner.scan_once()
    scan = state.cross_platform["last_scan"]
    assert scan["pairs"] == 2 and scan["priced"] == 1 and scan["opportunities"] == 0


# ------------------------------------------------- false matches (screenshot)
JUNK = [
    ("Shanghai Rolex Masters: Alex de Minaur vs Karen Khachanov",
     "Will Kenya and the US reach a critical minerals deal before Nov 1, 2026?"),
    ("Will Harry Kane win the 2026 Ballon d'Or?", "Saga Ballooners wins"),
    ("Jinan: Stefanos Sakellaridis vs Keegan Smith", "Millonarios wins by more than 2.5 goals?"),
    ("Santa Cruz 2: Joaquin Aguilar vs Felipe Meligeni Alves", "Crevelaro / Felipe Silva wins"),
    ("Wuhan Tennis Open: Yulia Putintseva vs Zeynep Sonmez", "Fontenel / Nishimura wins"),
]


@pytest.mark.parametrize("a,b", JUNK)
def test_unrelated_titles_do_not_score_as_a_match(a, b):
    """Team abbreviations such as 'no', 'min' and 'was' used to match inside ordinary words."""
    assert MarketMatcher().calculate_similarity(a, b) < 0.6


def test_team_abbreviations_only_count_as_whole_capitalised_words():
    m = MarketMatcher()
    assert m.extract_teams("Nov Minaur Khachanov was not here, no way") == []
    assert set(m.extract_teams("KC @ SEA")) == {"kansas city chiefs", "seattle seahawks"}
    assert set(m.extract_teams("Chiefs vs. Seahawks")) == {"kansas city chiefs", "seattle seahawks"}


def test_ordinary_text_is_not_categorised_as_sports():
    m = MarketMatcher()
    assert m._categorize_market("Will Kenya and the US reach a critical minerals deal before Nov 1?") != "sports"
    assert m._categorize_market("Chiefs vs. Seahawks") == "sports"


def test_same_game_matches_across_team_aliases():
    m = MarketMatcher()
    assert m.calculate_similarity("Chiefs vs. Seahawks", "Kansas City at Seattle winner?") >= 0.9


def test_a_totals_market_is_not_the_same_bet_as_a_winner_market():
    m = MarketMatcher()
    assert m.calculate_similarity("Chiefs vs. Seahawks: O/U 58.5", "Kansas City at Seattle winner?") < 0.6
    assert m.calculate_similarity("Chiefs vs. Seahawks: O/U 58.5",
                                  "Kansas City at Seattle: total points over 58.5") >= 0.9


def test_one_shared_team_is_a_different_game():
    m = MarketMatcher()
    assert m.calculate_similarity("Chiefs vs. Seahawks", "Chiefs vs. Raiders") < 0.6


def test_identical_titles_still_score_one():
    t = "Will Raphaël Glucksmann win the 2027 French presidential election?"
    assert MarketMatcher().calculate_similarity(t, t) == 1.0


# ------------------------------------------------------ Kalshi order book shapes
async def kalshi_book(payload):
    client = KalshiClient()

    async def fake_get(endpoint, params=None):
        return payload
    client._get = fake_get
    return await client.get_orderbook("KXTEST-1")


async def test_kalshi_book_legacy_cents_format():
    book = await kalshi_book({"orderbook": {"yes": [[40, 100], [42, 50]], "no": [[55, 80]]}})
    assert [(l.price, l.size) for l in book.yes_bids] == [(0.42, 50.0), (0.40, 100.0)]
    assert [(l.price, l.size) for l in book.no_bids] == [(0.55, 80.0)]


async def test_kalshi_book_fixed_point_dollar_format():
    book = await kalshi_book({"orderbook_fp": {
        "yes_dollars": [["0.4000", "100.00"], ["0.4200", "50.00"]], "no_dollars": [["0.5500", "80.00"]]}})
    assert [(l.price, l.size) for l in book.yes_bids] == [(0.42, 50.0), (0.40, 100.0)]
    assert [l.price for l in book.no_bids] == [0.55]


async def test_kalshi_book_prefers_fixed_point_when_both_are_present():
    book = await kalshi_book({"orderbook": {"yes": [[10, 1]], "no": [[20, 1]]},
                              "orderbook_fp": {"yes_dollars": [["0.4200", "5.00"]], "no_dollars": [["0.5500", "5.00"]]}})
    assert book.yes_bids[0].price == 0.42 and book.no_bids[0].price == 0.55


@pytest.mark.parametrize("payload", [
    {"orderbook": {"yes": None, "no": None}},
    {"orderbook": {}}, {"orderbook": None}, {"orderbook_fp": {"yes_dollars": None, "no_dollars": None}},
])
async def test_kalshi_empty_or_null_books_are_empty_not_errors(payload):
    book = await kalshi_book(payload)
    assert book is not None and book.yes_bids == [] and book.no_bids == []


async def test_kalshi_unknown_response_is_no_book_and_junk_levels_are_skipped():
    assert await kalshi_book({"something": "else"}) is None
    assert await kalshi_book({}) is None
    book = await kalshi_book({"orderbook": {"yes": [[0, 5], [101, 5], ["x", 1], [40, 0], [40], [45, 10]]}})
    assert [(l.price, l.size) for l in book.yes_bids] == [(0.45, 10.0)]


async def test_kalshi_book_converts_to_a_two_sided_unified_book():
    book = await kalshi_book({"orderbook_fp": {"yes_dollars": [["0.4000", "10"]], "no_dollars": [["0.5500", "10"]]}})
    unified = book.to_unified_orderbook()
    assert unified.best_bid_yes == 0.40 and round(unified.best_ask_yes, 2) == 0.45


# ------------------------------------------------- why a pair has no live prices
async def scan_with(config, state, fetch_a, fetch_b):
    from core.cross_platform_arb import CrossPlatformArbEngine
    from core.cross_platform_scanner import CrossPlatformScanner
    store = PairStore()
    pair = make_pair()
    store.add_many([pair])
    scanner = CrossPlatformScanner(CrossPlatformArbEngine(min_edge=0.02), store,
                                   {"polymarket": fetch_a, "kalshi": fetch_b}, state, config=config)
    await scanner.scan_once()
    return pair, state.cross_platform["last_scan"]


async def test_scan_says_which_platform_has_no_order_book(config, state):
    from tests.helpers import make_book

    async def poly(_): return make_book(0.40, 0.42)

    async def kalshi(_): return None
    pair, scan = await scan_with(config, state, poly, kalshi)
    assert pair.scan_note == "Kalshi: no order book"
    assert scan["priced"] == 0 and scan["why_unpriced"] == ["Kalshi: no order book"]


async def test_scan_says_when_a_fetch_fails(config, state):
    from tests.helpers import make_book

    async def poly(_): raise TimeoutError("slow")

    async def kalshi(_): return make_book(0.40, 0.42)
    pair, scan = await scan_with(config, state, poly, kalshi)
    assert pair.scan_note == "Polymarket: could not fetch (TimeoutError)" and scan["priced"] == 0


async def test_a_one_sided_book_is_not_counted_as_priced(config, state):
    from polymarket_client.models import OrderBookSide
    from tests.helpers import make_book

    async def poly(_): return make_book(0.40, 0.42)

    async def kalshi(_):
        book = make_book(0.40, 0.45)
        book.yes.bids = OrderBookSide([])                  # asks only, nobody is bidding
        return book
    pair, scan = await scan_with(config, state, poly, kalshi)
    assert "Kalshi: no bids yet" in pair.scan_note and scan["priced"] == 0


async def test_priced_pairs_have_an_empty_note_and_it_is_public(config, state):
    from core.pair_store import pair_to_public
    from tests.helpers import make_book

    async def poly(_): return make_book(0.40, 0.42)

    async def kalshi(_): return make_book(0.40, 0.42)
    pair, scan = await scan_with(config, state, poly, kalshi)
    assert pair.scan_note == "" and scan["priced"] == 1 and scan["why_unpriced"] == []
    pair.scan_note = "Kalshi: no order book"
    assert pair_to_public(pair)["scan_note"] == "Kalshi: no order book"
