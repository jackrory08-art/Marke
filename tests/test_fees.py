import pytest

from core.cross_platform_arb import CrossPlatformArbEngine
from core.fees import FeeModel, PredictItFees, walk_book
from polymarket_client.models import OrderBookSide, PriceLevel
from tests.helpers import make_book, make_pair, make_ref


def test_polymarket_kalshi_numbers_unchanged():
    f = FeeModel().breakdown("polymarket", "kalshi", 0.40, 0.55)
    # buy leg 1.5% of 0.40, sell leg 1% of 0.55, gas 0.02 x 2 orders
    assert f.buy_fee == pytest.approx(0.006)
    assert f.sell_fee == pytest.approx(0.0055)
    assert f.gas == pytest.approx(0.04)
    assert f.total == pytest.approx(0.0515)
    g = FeeModel().breakdown("kalshi", "polymarket", 0.40, 0.55)
    assert g.total == pytest.approx(0.40 * 0.01 + 0.55 * 0.015 + 0.04)


def test_predictit_worked_example_without_withdrawal_fee():
    # Buy YES on PredictIt at 0.40, sell YES on Polymarket at 0.55 (= buy NO at 0.45).
    f = FeeModel().breakdown("predictit", "polymarket", 0.40, 0.55)
    # PredictIt wins: 10% of 0.60 profit = 0.06. Poly leg: 1.5% of 0.45, plus 1 order of gas.
    assert f.profit_fee == pytest.approx(0.06)
    assert f.withdrawal_fee == 0
    assert f.total == pytest.approx(0.06 + 0.45 * 0.015 + 0.02)
    assert 0.15 - f.total == pytest.approx(0.06325)


def test_predictit_worked_example_with_withdrawal_fee():
    fm = FeeModel(predictit=PredictItFees(apply_withdrawal_fee=True))
    f = fm.breakdown("predictit", "polymarket", 0.40, 0.55)
    # payout after profit fee 0.94, then 5% withdrawal fee on it = 0.047
    assert f.withdrawal_fee == pytest.approx(0.047)
    assert f.total == pytest.approx(0.06 + 0.047 + 0.45 * 0.015 + 0.02)
    assert 0.15 - f.total == pytest.approx(0.01625)


def test_predictit_payout_helper():
    p = PredictItFees()
    assert p.payout_after_fees(0.40) == pytest.approx(1 - 0.10 * 0.60)
    assert PredictItFees(apply_withdrawal_fee=True).payout_after_fees(0.40) == pytest.approx(0.94 * 0.95)


def test_worst_case_state_is_taken():
    # Cheap PredictIt contract (profit large) vs expensive: the PI-wins state dominates
    cheap = FeeModel().breakdown("kalshi", "predictit", 0.30, 0.50)
    # kalshi buys YES at .30; selling YES on PI at .50 == buying NO on PI at .50
    assert cheap.profit_fee == pytest.approx(0.10 * 0.50)


def predictit_pair():
    return make_pair(make_ref("polymarket", "1"), make_ref("predictit", "9:9", rules=""))


def test_predictit_min_net_edge_filter():
    pair = predictit_pair()
    # a=polymarket book, b=predictit book. Buy YES on PredictIt at 0.40, sell on Polymarket at 0.55.
    poly = make_book(0.55, 0.57)
    pi = make_book(0.38, 0.40)
    strict = CrossPlatformArbEngine(min_edge=0.01, predictit_min_net_edge=0.10)
    assert strict.check_pair(pair, poly, pi) is None          # net 0.063 < 0.10
    ok = CrossPlatformArbEngine(min_edge=0.01, predictit_min_net_edge=0.05)
    opp = ok.check_pair(pair, poly, pi)
    assert opp and opp.buy_platform == "predictit" and opp.manual_trade
    assert opp.net_edge == pytest.approx(0.06325)
    assert opp.depth is None or opp.depth > 0


def test_walk_book_vwap():
    side = OrderBookSide([PriceLevel(0.50, 10), PriceLevel(0.60, 10)])
    assert walk_book(side, 5) == pytest.approx(0.50)
    assert walk_book(side, 20) == pytest.approx(0.55)
    assert walk_book(side, 40) == pytest.approx(0.55)   # shallow book: average of what exists
    assert walk_book(OrderBookSide([]), 5) is None
