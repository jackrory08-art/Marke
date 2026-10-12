import asyncio

from core.ai.service import build_ai_services
from core.pair_store import PairStore
from tests.conftest import _no_sleep
from tests.helpers import FakeProvider, make_pair, make_ref, verdict_json


async def wait_for(cond, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.01)


def build(db, ai_config, clock, provider):
    store, events = PairStore(), []
    svc = build_ai_services(ai_config, db, store, lambda t, d: events.append((t, d)),
                            provider=provider, clock=clock, sleep=_no_sleep, jitter=lambda: 0.0)
    return svc, store, events


async def test_queue_verifies_and_emits_events(db, ai_config, clock):
    provider = FakeProvider([verdict_json("identical", 0.95), verdict_json("different", 0.9)])
    svc, store, events = build(db, ai_config, clock, provider)
    ai_config.max_concurrency = 1
    pairs = [make_pair(make_ref("polymarket", f"q{i}", title=f"Queue market {i}")) for i in range(2)]
    store.add_many(pairs)
    svc.queue.start()
    try:
        assert svc.queue.enqueue_pending() == 2
        await wait_for(lambda: all(p.verification_status != "pending" for p in pairs))
        await wait_for(lambda: svc.queue.pending_count() == 0)
        await wait_for(lambda: events and events[-1][0] == "agent_state"
                       and events[-1][1]["state"] == "idle")
    finally:
        await svc.queue.stop()
    assert sorted(p.verification_status for p in pairs) == ["rejected", "verified"]
    types = [t for t, _ in events]
    assert types.count("verification_started") == 2 and types.count("verification_finished") == 2
    started = next(d for t, d in events if t == "verification_started")
    assert {"pair_id", "platforms", "titles", "position", "total"} <= set(started)
    finished = next(d for t, d in events if t == "verification_finished")
    assert {"pair_id", "status", "verdict", "confidence", "differences",
            "short_reason", "cached"} <= set(finished)
    assert any(t == "ai_budget" for t in types)
    assert any(t == "agent_state" and d["state"] == "verifying" for t, d in events)


async def test_edge_pairs_go_first(db, ai_config, clock):
    provider = FakeProvider()
    svc, store, events = build(db, ai_config, clock, provider)
    ai_config.max_concurrency = 1
    low = make_pair(make_ref("polymarket", "low", title="Low sim market"), similarity=0.95)
    edge = make_pair(make_ref("polymarket", "edge", title="Edge market"), similarity=0.6)
    edge.live_edge = True
    store.add_many([low, edge])
    svc.queue.enqueue(low.pair_id)
    svc.queue.enqueue(edge.pair_id)
    svc.queue.start()
    try:
        await wait_for(lambda: svc.queue.pending_count() == 0)
    finally:
        await svc.queue.stop()
    order = [d["pair_id"] for t, d in events if t == "verification_started"]
    assert order == [edge.pair_id, low.pair_id]


async def test_disable_marks_unverified_and_enable_requeues(db, ai_config, clock):
    provider = FakeProvider()
    svc, store, _ = build(db, ai_config, clock, provider)
    pair = make_pair()
    store.add_many([pair])
    svc.queue.start()
    try:
        svc.queue.enqueue(pair.pair_id)
        await wait_for(lambda: pair.verification_status == "verified")
        ai_config.enabled = False
        await svc.on_enabled_changed(False)
        assert pair.verification_status == "unverified"
        assert pair.verification["reason"] == "ai_disabled"
        ai_config.enabled = True
        await svc.on_enabled_changed(True)
        await wait_for(lambda: pair.verification_status == "verified")
        assert provider.calls == 1       # the second verdict came from the cache
    finally:
        await svc.queue.stop()
