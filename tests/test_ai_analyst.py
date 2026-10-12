import ast
import subprocess
import sys
from pathlib import Path

import pytest

from core.ai.analyst import (
    OpportunityAnalysis, OpportunityAnalyst, analysis_cache_key, snapshot_from_opportunity,
)
from core.ai.provider import ProviderError
from core.ai.runner import AIRunner, BudgetExhausted
from core.ai.schemas import MatchVerdict
from core.cross_platform_arb import CrossPlatformArbEngine
from core.cross_platform_scanner import CrossPlatformScanner
from core.pair_store import PairStore
from dashboard.state import DashboardState
from tests.conftest import _no_sleep
from tests.helpers import FakeProvider, make_book, make_pair, verdict_json

ANALYSIS = {
    "summary": "Buy YES on Polymarket and sell it on Kalshi.",
    "risks": [{"kind": "thin_depth", "severity": "medium", "detail": "Shallow book."}],
    "quality_score": 72,
}


def make_opp(status="verified", net_shift=0.0):
    pair = make_pair()
    pair.verification_status = status
    pair.verification = {"verdict": "identical", "confidence": 0.95, "differences": []}
    opp = CrossPlatformArbEngine(min_edge=0.02).check_pair(
        pair, make_book(0.40, 0.42), make_book(0.55, 0.57))
    opp.net_edge += net_shift
    return opp


@pytest.fixture
def analyst_factory(db, ai_config, clock):
    def factory(provider, emit=None):
        runner = AIRunner(provider, db, ai_config, clock=clock, sleep=_no_sleep, jitter=lambda: 0.0)
        return OpportunityAnalyst(runner, db, ai_config, clock=clock, emit=emit), runner
    return factory


async def test_only_verified_opportunities_are_analysed(analyst_factory):
    provider = FakeProvider([ANALYSIS])
    analyst, _ = analyst_factory(provider)
    for status in ("unverified", "rejected", "pending"):
        assert await analyst.analyse(make_opp(status)) is None
    assert provider.calls == 0
    result = await analyst.analyse(make_opp("verified"))
    assert result["quality_score"] == 72 and provider.calls == 1


async def test_numbers_are_unchanged_and_schema_has_no_price_fields(analyst_factory):
    assert set(OpportunityAnalysis.model_fields) == {"summary", "risks", "quality_score"}
    provider = FakeProvider([{**ANALYSIS, "buy_price": 0.01, "net_edge": 0.99}])  # extra keys ignored
    analyst, _ = analyst_factory(provider)
    opp = make_opp()
    before = (opp.buy_price, opp.sell_price, opp.net_edge, opp.gross_edge, dict(opp.fees),
              opp.suggested_size, opp.depth)
    result = await analyst.analyse(opp)
    after = (opp.buy_price, opp.sell_price, opp.net_edge, opp.gross_edge, dict(opp.fees),
             opp.suggested_size, opp.depth)
    assert before == after
    assert set(result) == {"summary", "risks", "quality_score", "model", "cached", "at"}
    system, prompt = provider.prompts[0]
    assert "authoritative" in system and "<opportunity>" in prompt
    assert f'"net_edge":{opp.net_edge}' in prompt.replace(" ", "")


def test_snapshot_is_frozen():
    snap = snapshot_from_opportunity(make_opp())
    with pytest.raises(Exception):
        snap.net_edge = 0.5


async def test_same_buckets_hit_cache_and_changed_buckets_miss(analyst_factory, clock):
    provider = FakeProvider([ANALYSIS])
    analyst, _ = analyst_factory(provider)
    await analyst.analyse(make_opp())
    await analyst.analyse(make_opp(net_shift=0.001))       # same 0.5pp bucket
    assert provider.calls == 1
    # A new bucket inside the minimum interval still reuses the latest analysis ...
    await analyst.analyse(make_opp(net_shift=0.02))
    assert provider.calls == 1
    # ... and re-analyses once the interval has passed.
    clock.advance(seconds=901)
    fresh = await analyst.analyse(make_opp(net_shift=0.02))
    assert provider.calls == 2 and not fresh["cached"]


def test_cache_key_buckets():
    refs = lambda o: (o.market_pair.ref_a, o.market_pair.ref_b)  # noqa: E731
    base = make_opp()
    k = lambda o: analysis_cache_key("p", "m", snapshot_from_opportunity(o), refs(o))  # noqa: E731
    assert k(base) == k(make_opp(net_shift=0.001))
    assert k(base) != k(make_opp(net_shift=0.01))
    deep = make_opp()
    deep.depth = 5000
    assert k(base) != k(deep)
    later = make_opp()
    later.time_to_expiry = (base.time_to_expiry or 0) + 3 * 86400
    assert k(base) != k(later)


async def test_errors_leave_opportunity_without_score(analyst_factory):
    provider = FakeProvider([ProviderError("boom")])
    analyst, _ = analyst_factory(provider)
    assert await analyst.analyse(make_opp()) is None


async def test_attach_and_event(analyst_factory, db, config):
    events = []
    provider = FakeProvider([ANALYSIS])
    analyst, _ = analyst_factory(provider, emit=lambda t, d: events.append((t, d)))
    state, store = DashboardState(), PairStore()

    async def poly(_): return make_book(0.40, 0.42)
    async def kalshi(_): return make_book(0.55, 0.57)
    scanner = CrossPlatformScanner(CrossPlatformArbEngine(min_edge=0.02), store,
                                   {"polymarket": poly, "kalshi": kalshi}, state, db=db, config=config)
    pair = make_pair()
    pair.verification_status = "verified"
    store.add_many([pair])
    scanner.analyst = analyst
    await scanner.scan_once()
    import asyncio
    for _ in range(50):
        await asyncio.sleep(0.01)
        if state.cross_platform["cross_opportunities"][0]["analysis"]:
            break
    opp = state.cross_platform["cross_opportunities"][0]
    assert opp["analysis"]["summary"] and opp["quality_score"] == 72
    ready = [d for t, d in events if t == "analysis_ready"]
    assert len(ready) == 1 and ready[0]["quality_score"] == 72 and ready[0]["pair_id"] == pair.pair_id
    await scanner.scan_once()          # next scan keeps the analysis and doesn't re-announce it
    await asyncio.sleep(0.05)
    assert provider.calls == 1
    assert state.cross_platform["cross_opportunities"][0]["quality_score"] == 72


async def test_verifier_reserve_is_respected(analyst_factory, ai_config):
    ai_config.daily_call_budget = 10
    ai_config.verifier_reserve_pct = 40      # analyses may use at most 6 of the 10 calls
    provider = FakeProvider([ANALYSIS])
    analyst, runner = analyst_factory(provider)
    for _ in range(6):
        await runner.call(system="s", prompt="p", schema=OpportunityAnalysis, purpose="analyze")
    with pytest.raises(BudgetExhausted):
        await runner.call(system="s", prompt="p", schema=OpportunityAnalysis, purpose="analyze")
    assert await analyst.analyse(make_opp()) is None       # blocked, no crash
    provider.script = [verdict_json()]
    for _ in range(4):                                       # verification still has its 4
        await runner.call(system="s", prompt="p", schema=MatchVerdict, purpose="verify")
    with pytest.raises(BudgetExhausted):
        await runner.call(system="s", prompt="p", schema=MatchVerdict, purpose="verify")


async def test_analysis_disabled_flag(analyst_factory, ai_config):
    ai_config.analysis_enabled = False
    provider = FakeProvider([ANALYSIS])
    analyst, _ = analyst_factory(provider)
    assert await analyst.analyse(make_opp()) is None and provider.calls == 0


# ----------------------------------------------------------------- isolation
FORBIDDEN = ("core.execution", "core.risk_manager", "core.portfolio", "core.arb_engine",
             "polymarket_client.api", "kalshi_client.api", "predictit_client.api",
             "kalshi_client", "predictit_client")
AI_DIR = Path(__file__).resolve().parent.parent / "core" / "ai"


def imported_modules(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for a in node.names:
                yield f"{node.module}.{a.name}"


def test_ai_package_imports_no_trading_code():
    files = sorted(AI_DIR.glob("*.py"))
    assert len(files) >= 8
    for f in files:
        for mod in imported_modules(f):
            assert not any(mod == bad or mod.startswith(bad + ".") for bad in FORBIDDEN), \
                f"{f.name} imports {mod}"


def test_ai_package_pulls_no_trading_code_transitively():
    code = ("import sys, core.ai.service, core.ai.analyst, core.ai.verifier, core.ai.queue, "
            "core.ai.gemini, core.ai.mock, core.ai.mock_analysis\n"
            "bad = ['core.execution','core.risk_manager','core.portfolio','core.arb_engine',"
            "'polymarket_client.api','kalshi_client.api','predictit_client.api']\n"
            "print(','.join(m for m in bad if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True).stdout.strip()
    assert out == ""
