import asyncio

from core.ai.mock import MockProvider
from core.ai.schemas import MatchVerdict
from core.ai.verifier import SYSTEM_PROMPT, build_prompt, evaluate_gate
from core.cross_platform_arb import CrossPlatformArbEngine
from core.simulation_pairs import DemoMarkets
from utils.config_loader import get_default_config


async def verdicts():
    cfg = get_default_config().ai
    out = {}
    for pair in DemoMarkets().pairs():
        r = await MockProvider().generate_structured(
            system=SYSTEM_PROMPT, prompt=build_prompt((pair.ref_a, pair.ref_b)), schema=MatchVerdict)
        diffs = [d.model_dump() for d in r.value.differences]
        out[pair.pair_id] = evaluate_gate(r.value.verdict, r.value.confidence, diffs,
                                          (pair.ref_a, pair.ref_b), cfg)
    return out


async def test_demo_covers_every_gate_outcome():
    result = await verdicts()
    assert result["polymarket:sim-fed|kalshi:KXFEDCUT-27MAR"] == ("verified", "")
    assert result["polymarket:sim-eth|kalshi:KXETH-30JUN-T6000"] == ("rejected", "different")
    assert result["polymarket:sim-senate|kalshi:KXFARM-FAIL"] == ("rejected", "inverse_polarity")
    assert {s for s, _ in result.values()} == {"verified", "rejected"}
    assert len(result) >= 10


async def test_demo_has_real_edges_across_all_three_platforms():
    demo = DemoMarkets()
    engine = CrossPlatformArbEngine(min_edge=0.02, predictit_min_net_edge=0.05)
    found = {}
    for pair in demo.pairs():
        a = await demo.fetcher(pair.platform_a)(pair.market_a_id)
        b = await demo.fetcher(pair.platform_b)(pair.market_b_id)
        opp = engine.check_pair(pair, a, b, record=False)
        if opp:
            found[pair.pair_id] = opp
    platforms = {p for pid in found for p in pid.replace("|", ":").split(":") if p in ("polymarket", "kalshi", "predictit")}
    assert platforms == {"polymarket", "kalshi", "predictit"}
    pi = [o for o in found.values() if o.manual_trade]
    assert pi and all(o.depth is None for o in pi)           # PredictIt publishes no size


async def test_demo_books_wobble_but_stay_valid():
    demo = DemoMarkets()
    fetch = demo.fetcher("polymarket")
    b1, b2 = await fetch("sim-fed"), await fetch("sim-fed")
    assert b1.best_ask_yes != b2.best_ask_yes
    assert 0 < b1.best_bid_yes < b1.best_ask_yes < 1
    assert await fetch("unknown") is None
