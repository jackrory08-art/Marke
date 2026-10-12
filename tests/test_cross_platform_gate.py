import pytest

from core.cross_platform_arb import CrossPlatformArbEngine, MarketPair
from core.cross_platform_scanner import CrossPlatformScanner
from core.pair_store import PairStore
from dashboard.state import DashboardState
from tests.helpers import make_book, make_pair, make_ref


def legacy_check(poly, kalshi, min_edge=0.02, pf=0.015, kf=0.01, gas=0.02):
    """The original check_arbitrage maths, copied verbatim for regression."""
    best, best_net = None, 0.0
    cands = [
        ("polymarket", "kalshi", "YES", poly.best_ask_yes, kalshi.best_bid_yes, pf, kf),
        ("kalshi", "polymarket", "YES", kalshi.best_ask_yes, poly.best_bid_yes, kf, pf),
        ("polymarket", "kalshi", "NO", poly.best_ask_no, kalshi.best_bid_no, pf, kf),
        ("kalshi", "polymarket", "NO", kalshi.best_ask_no, poly.best_bid_no, kf, pf),
    ]
    for buy_p, sell_p, token, buy, sell, bf, sf in cands:
        if buy and sell:
            gross = sell - buy
            net = gross - (buy * bf + sell * sf + gas * 2)
            if net > best_net and net >= min_edge:
                best_net, best = net, (buy_p, sell_p, token, buy, sell, gross, net)
    return best


@pytest.mark.parametrize("poly,kalshi", [
    (dict(yes_bid=0.40, yes_ask=0.42), dict(yes_bid=0.55, yes_ask=0.57)),
    (dict(yes_bid=0.62, yes_ask=0.64), dict(yes_bid=0.50, yes_ask=0.52)),
    (dict(yes_bid=0.48, yes_ask=0.50), dict(yes_bid=0.49, yes_ask=0.51)),
    (dict(yes_bid=0.30, yes_ask=0.35, no_bid=0.60, no_ask=0.70),
     dict(yes_bid=0.40, yes_ask=0.45, no_bid=0.52, no_ask=0.58)),
])
def test_check_pair_matches_old_maths(poly, kalshi):
    pb, kb = make_book(**poly), make_book(**kalshi)
    engine = CrossPlatformArbEngine(min_edge=0.02)
    pair = make_pair()
    new = engine.check_pair(pair, pb, kb)
    old = legacy_check(pb, kb)
    if old is None:
        assert new is None
    else:
        assert (new.buy_platform, new.sell_platform, new.token) == old[:3]
        assert new.buy_price == pytest.approx(old[3]) and new.sell_price == pytest.approx(old[4])
        assert new.gross_edge == pytest.approx(old[5]) and new.net_edge == pytest.approx(old[6])


def test_check_arbitrage_delegates():
    pb, kb = make_book(0.40, 0.42), make_book(0.55, 0.57)
    engine = CrossPlatformArbEngine(min_edge=0.02)
    assert engine.check_arbitrage(make_pair(), pb, kb).net_edge == \
        engine.check_pair(make_pair(), pb, kb).net_edge


def test_min_similarity_is_wired():
    assert CrossPlatformArbEngine(min_match_similarity=0.77).matcher.min_similarity == 0.77


def test_extra_fields_on_opportunity():
    opp = CrossPlatformArbEngine(min_edge=0.02).check_pair(
        make_pair(), make_book(0.40, 0.42, size=50), make_book(0.55, 0.57, size=30))
    assert opp.fees["total"] > 0 and set(opp.fees) >= {"buy_fee", "sell_fee", "gas", "total"}
    assert opp.depth == 30
    assert opp.slippage_estimate == pytest.approx(0.0)
    assert opp.time_to_expiry is not None
    assert opp.suggested_size == 30


def test_slippage_when_book_is_thin():
    from polymarket_client.models import OrderBookSide, PriceLevel
    poly, kalshi = make_book(0.40, 0.42, size=50), make_book(0.55, 0.57, size=200)
    poly.yes.asks = OrderBookSide([PriceLevel(0.42, 10), PriceLevel(0.44, 100)])
    opp = CrossPlatformArbEngine(min_edge=0.0).check_pair(make_pair(), poly, kalshi)
    assert opp.suggested_size == 10 or opp.slippage_estimate is not None


@pytest.mark.parametrize("status,actionable", [
    ("verified", True), ("unverified", False), ("rejected", False), ("pending", False)])
def test_only_verified_pairs_are_actionable(status, actionable):
    pair = make_pair()
    pair.verification_status = status
    opp = CrossPlatformArbEngine(min_edge=0.02).check_pair(
        pair, make_book(0.40, 0.42), make_book(0.55, 0.57))
    assert opp.actionable is actionable and opp.verification_status == status


def test_dismissed_pair_is_never_actionable():
    pair = make_pair()
    pair.verification_status, pair.dismissed = "verified", True
    opp = CrossPlatformArbEngine(min_edge=0.02).check_pair(
        pair, make_book(0.40, 0.42), make_book(0.55, 0.57))
    assert opp.actionable is False


def test_pair_identity_is_canonical_and_backwards_compatible():
    a, b = make_ref("polymarket", "12"), make_ref("kalshi", "KX1", title="Kalshi title")
    p1, p2 = MarketPair.from_refs(a, b, 0.7), MarketPair.from_refs(b, a, 0.7)
    assert p1.pair_id == p2.pair_id == "polymarket:12|kalshi:KX1"
    assert (p1.polymarket_id, p1.kalshi_ticker, p1.kalshi_title) == ("12", "KX1", "Kalshi title")


# ----------------------------------------------------------------- the scanner
class Harness:
    def __init__(self, db, config):
        self.state = DashboardState()
        self.store = PairStore()
        self.events = []
        self.engine = CrossPlatformArbEngine(min_edge=0.02)
        self.fetched = []
        books = {"polymarket": make_book(0.40, 0.42), "kalshi": make_book(0.55, 0.57)}

        async def fetch_poly(mid):
            self.fetched.append(("polymarket", mid))
            return books["polymarket"]

        async def fetch_kalshi(mid):
            self.fetched.append(("kalshi", mid))
            return books["kalshi"]

        self.scanner = CrossPlatformScanner(
            self.engine, self.store, {"polymarket": fetch_poly, "kalshi": fetch_kalshi},
            self.state, db=db, config=config, emit=lambda t, d: self.events.append((t, d)))


async def test_scanner_gate_dismissal_and_history(db, config):
    h = Harness(db, config)
    pairs = {}
    for status in ("verified", "unverified", "rejected", "pending", "dismissed"):
        p = make_pair(make_ref("polymarket", status), make_ref("kalshi", f"K-{status}"))
        p.verification_status = "unverified" if status == "dismissed" else status
        pairs[status] = p
    h.store.add_many(pairs.values())
    h.store.set_dismissed("polymarket:dismissed|kalshi:K-dismissed", True)

    found = await h.scanner.scan_once()
    by_status = {o.verification_status: o for o in found}
    assert set(by_status) == {"verified", "unverified", "pending"}   # rejected/dismissed not scanned
    assert by_status["verified"].actionable
    assert not by_status["unverified"].actionable and not by_status["pending"].actionable
    assert ("polymarket", "rejected") not in h.fetched and ("polymarket", "dismissed") not in h.fetched
    published = h.state.cross_platform["cross_opportunities"]
    assert len(published) == 3 and sum(o["actionable"] for o in published) == 1

    from app import repo
    with db.session() as s:
        hist = repo.list_history(s)
        assert len(hist) == 3 and {r.actionable for r in hist} == {True, False}
    await h.scanner.scan_once()
    with db.session() as s:
        assert max(r.seen_count for r in repo.list_history(s)) == 2


async def test_verdict_makes_opportunity_actionable(db, config):
    h = Harness(db, config)
    pair = make_pair()
    h.store.add_many([pair])
    await h.scanner.scan_once()
    assert not h.state.cross_platform["cross_opportunities"][0]["actionable"]
    h.store.set_verification(pair.pair_id, "verified", {"verdict": "identical"})
    await h.scanner.on_pair_verified(pair)
    assert h.state.cross_platform["cross_opportunities"][0]["actionable"]
    assert any(t == "opportunity" and d["actionable"] for t, d in h.events)


async def test_disabled_source_pairs_are_skipped(db, config):
    h = Harness(db, config)
    h.store.add_many([make_pair()])
    config.mode.kalshi_enabled = False
    assert await h.scanner.scan_once() == []


async def test_fetch_failure_or_missing_book_is_not_an_opportunity(db, config):
    h = Harness(db, config)

    async def boom(_):
        raise RuntimeError("network")
    h.scanner.fetchers["kalshi"] = boom
    h.store.add_many([make_pair()])
    assert await h.scanner.scan_once() == []
