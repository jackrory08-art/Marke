import json
from pathlib import Path

import httpx
import pytest

from app.config import PredictItConfig
from core.cross_platform_arb import CrossPlatformArbEngine
from core.fees import level_size, top_of_book_size
from predictit_client.api import MIN_POLL_INTERVAL_S, USER_AGENT, PredictItClient, build_predictit_client
from predictit_client.models import contract_to_orderbook, parse_all
from tests.helpers import FakeProvider, make_book, make_pair, make_ref, verdict_json

FIXTURE = Path(__file__).parent / "fixtures" / "predictit_all.json"


def payload():
    return json.loads(FIXTURE.read_text())


def recase(value, fn):
    if isinstance(value, dict):
        return {fn(k): recase(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [recase(v, fn) for v in value]
    return value


# ------------------------------------------------------------------ parsing
def test_fixture_parses_markets_and_contracts():
    markets = parse_all(payload())
    assert [m.id for m in markets] == ["7456", "7822", "7001"]
    assert [len(m.contracts) for m in markets] == [3, 1, 1]
    dem = markets[0].contracts[0]
    assert (dem.best_buy_yes_cost, dem.best_buy_no_cost) == (0.48, 0.54)
    assert markets[0].is_open and not markets[2].is_open


def test_multi_contract_market_maps_to_one_ref_per_contract():
    refs = parse_all(payload())[0].to_comparable()
    assert [r.market_id for r in refs] == ["7456:28001", "7456:28002", "7456:28003"]
    assert refs[0].title == "Which party will win the 2028 US presidential election? — Democratic"
    assert all(r.platform == "predictit" and r.rules_text == "" and not r.has_rules for r in refs)
    assert refs[0].end_date.startswith("2028-11-07") and refs[0].outcome_label == "YES = Democratic"


def test_single_contract_title_is_not_duplicated_and_closed_markets_are_skipped():
    markets = parse_all(payload())
    refs = markets[1].to_comparable()
    assert len(refs) == 1 and refs[0].title == markets[1].name
    assert markets[2].to_comparable() == []


def test_na_date_and_null_prices():
    other = parse_all(payload())[0].contracts[2]
    assert other.date_end is None
    assert other.best_buy_no_cost is None and other.best_sell_yes_cost is None
    assert parse_all(payload())[0].to_comparable()[2].end_date == ""
    book = contract_to_orderbook("7456:28003", other)
    assert book.best_ask_yes == 0.04 and book.best_ask_no is None
    assert book.best_bid_no == 0.96


@pytest.mark.parametrize("fn", [
    lambda k: k[0].upper() + k[1:],        # PascalCase
    str.lower,                             # lowercase
    str.upper,                             # UPPER
    lambda k: "".join("_" + c.lower() if c.isupper() else c for c in k),   # snake_case
])
def test_casing_variants_parse_identically(fn):
    base = [(m.id, [(c.id, c.best_buy_yes_cost, c.best_sell_no_cost, c.date_end) for c in m.contracts])
            for m in parse_all(payload())]
    other = [(m.id, [(c.id, c.best_buy_yes_cost, c.best_sell_no_cost, c.date_end) for c in m.contracts])
             for m in parse_all(recase(payload(), fn))]
    assert other == base


def test_bare_list_junk_and_zero_prices_are_tolerated():
    raw = payload()["markets"]
    assert len(parse_all(raw)) == 3
    junk = [None, 5, {"name": "no id"}, {"id": 1, "name": "x", "contracts": [None, {"id": 2, "status": "Open", "bestBuyYesCost": 0, "bestBuyNoCost": "n/a"}]}]
    markets = parse_all({"markets": junk})
    assert len(markets) == 1 and markets[0].contracts[0].best_buy_yes_cost is None
    assert contract_to_orderbook("1:2", markets[0].contracts[0]) is None     # no usable price
    assert parse_all({}) == [] and parse_all(None) == []


def test_synthetic_book_has_asks_bids_and_unknown_size():
    dem = parse_all(payload())[0].contracts[0]
    book = contract_to_orderbook("7456:28001", dem)
    assert (book.best_ask_yes, book.best_ask_no) == (0.48, 0.54)
    assert (book.best_bid_yes, book.best_bid_no) == (0.46, 0.52)       # from bestSell*
    assert len(book.yes.asks.levels) == 1
    assert level_size(book.yes.asks.levels[0]) is None and top_of_book_size(book.yes.asks) is None
    no_sell = parse_all(payload())[1].contracts[0]
    no_sell.best_sell_yes_cost = no_sell.best_sell_no_cost = None
    book = contract_to_orderbook("x", no_sell)
    assert book.best_bid_yes == pytest.approx(1 - 0.73)                 # complement fallback


def test_predictit_opportunity_has_unknown_depth_and_manual_flag():
    pair = make_pair(make_ref("polymarket", "1"), make_ref("predictit", "7456:28001", rules=""))
    pi = contract_to_orderbook("7456:28001", parse_all(payload())[0].contracts[0])
    poly = make_book(0.66, 0.68)      # Polymarket pays much more for YES than PredictIt asks
    opp = CrossPlatformArbEngine(min_edge=0.01, predictit_min_net_edge=0.05).check_pair(pair, poly, pi)
    assert opp and opp.buy_platform == "predictit" and opp.manual_trade
    assert opp.depth is None
    assert opp.suggested_size <= 850 / opp.buy_price


# ------------------------------------------------------------------- client
def make_client(handler, **cfg):
    config = PredictItConfig(enabled=True, **cfg)
    clock = {"t": 1000.0}
    sleeps = []

    async def sleep(s):
        sleeps.append(s)
    client = PredictItClient(config, transport=httpx.MockTransport(handler), sleep=sleep,
                             monotonic=lambda: clock["t"])
    return client, clock, sleeps


async def test_poll_interval_cache_is_honoured():
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, json=payload())
    client, clock, _ = make_client(handler, poll_interval_s=10)   # below the floor
    await client.get_markets()
    clock["t"] += 30
    await client.get_markets()
    assert client.request_count == 1 and client.poll_interval_s == MIN_POLL_INTERVAL_S
    clock["t"] += 31
    await client.get_markets()
    assert client.request_count == 2
    await client.get_markets(force=True)
    assert client.request_count == 3
    assert seen[0] == USER_AGENT and "Marke" in USER_AGENT
    await client.aclose()


async def test_503_then_200_succeeds():
    responses = iter([httpx.Response(503), httpx.Response(200, json=payload())])
    client, _, sleeps = make_client(lambda r: next(responses))
    markets = await client.get_markets()
    assert len(markets) == 3 and client.request_count == 2 and sleeps == [1.0]
    assert client.get_orderbook("7456:28001") is not None
    assert client.get_orderbook("7001:90001") is None            # closed market has no book
    assert len(client.comparable_markets()) == 4                 # 3 + 1 open contracts
    await client.aclose()


async def test_connection_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=payload())
    client, _, _ = make_client(handler)
    assert len(await client.get_markets()) == 3 and len(calls) == 3
    await client.aclose()


async def test_persistent_failure_serves_last_good_data_and_backs_off():
    state = {"ok": True}

    def handler(request):
        return httpx.Response(200, json=payload()) if state["ok"] else httpx.Response(500)
    client, clock, _ = make_client(handler)
    assert len(await client.get_markets()) == 3
    state["ok"] = False
    clock["t"] += 61
    assert len(await client.get_markets()) == 3            # last good data, no exception
    before = client.request_count
    clock["t"] += 10
    await client.get_markets()
    assert client.request_count == before                  # backed off for a full interval
    await client.aclose()


async def test_client_error_is_not_retried():
    client, _, _ = make_client(lambda r: httpx.Response(404))
    assert await client.get_markets() == []
    assert client.request_count == 1
    await client.aclose()


def test_disabled_flag_means_no_client():
    from utils.config_loader import get_default_config
    cfg = get_default_config()
    assert cfg.predictit.enabled is False and build_predictit_client(cfg) is None
    cfg.predictit.enabled = True
    assert isinstance(build_predictit_client(cfg), PredictItClient)


# ------------------------------------------------------------ the gate
async def test_missing_rules_are_flagged_in_the_prompt_and_cap_the_verdict(make_verifier):
    provider = FakeProvider([verdict_json("identical", 0.85)])
    verifier, _, _ = make_verifier(provider)
    pair = make_pair(make_ref("polymarket", "1"),
                     parse_all(payload())[0].to_comparable()[0])
    result = await verifier.verify(pair)
    _, prompt = provider.prompts[0]
    assert '"rules_available": false' in prompt and "missing_rules" in provider.prompts[0][0]
    assert result.status == "rejected" and result.reason == "below_threshold"
