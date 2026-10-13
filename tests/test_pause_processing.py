"""The 'pause processing' switch: setting, persistence, UI state and the loops that honour it."""

import asyncio
import threading
import time

from app import repo
from app.settings import apply_overrides
from core.ai.service import build_ai_services
from core.cross_platform_arb import CrossPlatformArbEngine, MarketMatcher
from core.cross_platform_scanner import CrossPlatformScanner
from core.data_feed import DataFeed
from core.pair_store import PairStore
from tests.conftest import _no_sleep
from tests.helpers import FakeProvider, make_book, make_pair, make_ref, verdict_json


# ------------------------------------------------------------ setting + API
def test_pause_defaults_to_off_and_is_reported(logged_in_client, config):
    assert config.mode.paused is False
    assert logged_in_client.get("/api/state").json()["paused"] is False
    assert logged_in_client.get("/api/settings").json()["settings"]["mode.paused"] is False


def test_pause_and_resume_via_settings_persist_and_audit(logged_in_client, config, db, state):
    res = logged_in_client.patch("/api/settings", json={"mode.paused": True})
    assert res.status_code == 200 and res.json()["settings"]["mode.paused"] is True
    assert config.mode.paused is True and state.paused is True
    assert logged_in_client.get("/api/state").json()["paused"] is True
    with db.session() as s:
        assert repo.get_overrides(s)["mode.paused"] is True
        keys = [a.detail["key"] for a in repo.list_audit(s) if a.event == "config_change"]
    assert "mode.paused" in keys

    assert logged_in_client.patch("/api/settings", json={"mode.paused": False}).status_code == 200
    assert config.mode.paused is False and state.paused is False


def test_pause_rejects_non_boolean(logged_in_client, config):
    assert logged_in_client.patch("/api/settings", json={"mode.paused": "yes"}).status_code == 422
    assert config.mode.paused is False


def test_pause_survives_restart(db, config):
    with db.session() as s:
        repo.set_override(s, "mode.paused", True, "owner")
    assert apply_overrides(config, db) == {"mode.paused": True}
    assert config.mode.paused is True


def test_pausing_tells_the_ui_what_the_agent_is_doing(state):
    state.set_paused(True)
    assert state.paused is True and state.agent_state["detail"] == "Paused"
    state.set_paused(True)                       # no change, no new event
    state.set_paused(False)
    assert state.paused is False and state.agent_state["detail"] == "Resuming"


# ---------------------------------------------------------- the loops obey it
async def test_scanner_skips_cycles_while_paused(config, state):
    calls = []
    store = PairStore()
    store.add_many([make_pair()])

    async def book(_): return make_book(0.40, 0.42)
    scanner = CrossPlatformScanner(
        CrossPlatformArbEngine(min_edge=0.02), store, {"polymarket": book, "kalshi": book},
        state, config=config)

    async def fake_scan():
        calls.append(1)
    scanner.scan_once = fake_scan

    config.mode.paused = True
    task = asyncio.create_task(scanner.run(0.01))
    await asyncio.sleep(0.08)
    assert calls == []
    config.mode.paused = False
    await asyncio.sleep(0.08)
    scanner.stop()
    task.cancel()
    assert calls, "scanning should resume"


async def test_ai_queue_holds_work_while_paused(db, ai_config, clock, config):
    provider = FakeProvider([verdict_json("identical", 0.95)])
    store = PairStore()
    svc = build_ai_services(ai_config, db, store, lambda *_: None, provider=provider,
                            clock=clock, sleep=_no_sleep, jitter=lambda: 0.0)
    svc.queue.pause_check = lambda: config.mode.paused
    pair = make_pair(make_ref("polymarket", "q1", title="Paused queue market"))
    store.add_many([pair])
    config.mode.paused = True
    svc.queue.start()
    try:
        svc.queue.enqueue_pending()
        await asyncio.sleep(0.2)
        assert pair.verification_status == "pending"
        config.mode.paused = False
        for _ in range(300):                      # the worker re-checks once a second
            if pair.verification_status != "pending":
                break
            await asyncio.sleep(0.02)
        assert pair.verification_status != "pending"
    finally:
        await svc.queue.stop()


def test_matcher_blocks_in_its_gate_until_released():
    """Matching runs in a worker thread: the gate must hold it, and release it, without losing work."""
    paused = threading.Event()
    paused.set()
    entered = []

    def gate():
        entered.append(1)
        while paused.is_set():
            time.sleep(0.01)

    matcher = MarketMatcher(min_similarity=0.5)
    matcher.pause_gate = gate
    matcher._categorize_market = lambda text: "sports"   # 'other' is skipped by the matcher
    refs_a = [make_ref("polymarket", f"a{i}", title=f"Will Team Alpha win match number {i}") for i in range(3)]
    refs_b = [make_ref("kalshi", f"b{i}", title=f"Will Team Alpha win match number {i}") for i in range(3)]
    result = {}
    t = threading.Thread(target=lambda: result.setdefault(
        "pairs", asyncio.run(matcher.match_refs(refs_a, refs_b))))
    t.start()
    time.sleep(0.15)
    assert t.is_alive() and "pairs" not in result, "matching must wait while paused"
    paused.clear()
    t.join(timeout=10)
    assert not t.is_alive() and "pairs" in result
    assert len(entered) >= 1


def test_data_feed_reports_pause_from_config(config):
    feed = DataFeed(client=None, market_ids=[], config=config)
    assert feed._paused() is False
    config.mode.paused = True
    assert feed._paused() is True
    assert DataFeed(client=None, market_ids=[], config=None)._paused() is False
