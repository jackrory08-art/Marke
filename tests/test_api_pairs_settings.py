import pytest

from app import repo
from core.ai.service import build_ai_services
from core.cross_platform_arb import CrossPlatformArbEngine
from core.cross_platform_scanner import CrossPlatformScanner
from core.pair_store import PairStore
from tests.helpers import FakeProvider, make_book, make_pair, make_ref


@pytest.fixture
def wired(app, state, db, config, ai_config, clock, logged_in_client):
    store = PairStore()
    state.pair_store = store
    state.ai = build_ai_services(ai_config, db, store, state.emit, provider=FakeProvider(), clock=clock)
    engine = CrossPlatformArbEngine(min_edge=0.02)

    async def poly(_): return make_book(0.40, 0.42)
    async def kalshi(_): return make_book(0.55, 0.57)
    state.scanner = CrossPlatformScanner(
        engine, store, {"polymarket": poly, "kalshi": kalshi}, state, db=db, config=config,
        emit=state.emit)
    state.setting_hooks["ai.enabled"] = lambda v: state.ai.on_enabled_changed(v, state.scanner)
    pair = make_pair()
    pair.verification_status = "verified"
    store.add_many([pair])
    return logged_in_client, state, pair


def test_pairs_listing_filters(wired):
    c, state, pair = wired
    body = c.get("/api/pairs").json()
    assert body["counts"]["verified"] == 1 and body["pairs"][0]["pair_id"] == pair.pair_id
    assert body["pairs"][0]["refs"][0]["rules_text"]
    assert len(c.get("/api/pairs?status=rejected").json()["pairs"]) == 0
    assert len(c.get("/api/pairs?platform=kalshi").json()["pairs"]) == 1
    assert len(c.get("/api/pairs?platform=predictit").json()["pairs"]) == 0


def test_dismiss_and_undismiss_persist(wired, db):
    c, state, pair = wired
    url = f"/api/pairs/{pair.pair_id}/dismiss"
    res = c.post(url)
    assert res.status_code == 200 and res.json()["status"] == "dismissed"
    with db.session() as s:
        assert repo.dismissed_pair_keys(s) == {pair.pair_id}
    assert c.get("/api/pairs?status=dismissed").json()["pairs"][0]["pair_id"] == pair.pair_id
    res = c.delete(url)
    assert res.json()["status"] == "verified"
    with db.session() as s:
        assert repo.dismissed_pair_keys(s) == set()
    assert c.post("/api/pairs/nope/dismiss").status_code == 404


def test_pair_mutations_need_csrf(wired):
    c, _, pair = wired
    token = c.headers.pop("X-CSRF-Token")
    assert c.post(f"/api/pairs/{pair.pair_id}/dismiss").status_code == 403
    c.headers["X-CSRF-Token"] = token


def test_reverify_queues_pair(wired):
    c, state, pair = wired
    res = c.post(f"/api/pairs/{pair.pair_id}/reverify")
    assert res.status_code == 202 and res.json()["verification_status"] == "pending"
    assert state.ai.queue.pending_count() == 1


async def test_opportunities_endpoint_includes_gate_fields(wired):
    c, state, pair = wired
    await state.scanner.scan_once()
    body = c.get("/api/opportunities").json()
    opp = body["opportunities"][0]
    assert opp["verification_status"] == "verified" and opp["actionable"] is True
    assert opp["fees"]["total"] > 0 and "analysis" in opp and "depth" in opp
    assert len(c.get("/api/opportunities?actionable=false").json()["opportunities"]) == 0
    assert len(c.get("/api/opportunities?status=verified&platform=kalshi").json()["opportunities"]) == 1
    one = c.get(f"/api/opportunities/{opp['id']}")
    assert one.status_code == 200 and one.json()["id"] == opp["id"]
    assert c.get("/api/opportunities/missing").status_code == 404
    hist = c.get("/api/opportunities/history").json()["history"]
    assert hist and hist[0]["id"] == opp["id"]


def test_bundle_opportunities_are_listed(wired):
    c, state, _ = wired
    state.add_opportunity({"type": "bundle_long", "market_id": "m1", "edge": 0.03})
    items = c.get("/api/opportunities").json()["opportunities"]
    bundle = [o for o in items if o["kind"] == "bundle"][0]
    assert bundle["verification_status"] == "n/a" and bundle["actionable"] is True


def test_settings_get_and_patch_with_audit(wired, config, db):
    c, state, _ = wired
    body = c.get("/api/settings").json()
    assert body["readonly"]["trading_mode"] == "dry_run"
    assert "trading_mode" not in body["settings"]
    res = c.patch("/api/settings", json={"ai.min_confidence": 0.85, "predictit.enabled": True})
    assert res.status_code == 200
    assert config.ai.min_confidence == 0.85 and config.predictit.enabled is True
    with db.session() as s:
        assert repo.get_overrides(s) == {"ai.min_confidence": 0.85, "predictit.enabled": True}
        events = [(a.event, a.detail["key"]) for a in repo.list_audit(s) if a.event == "config_change"]
    assert ("config_change", "ai.min_confidence") in events


@pytest.mark.parametrize("payload", [
    {"trading_mode": "live"}, {"mode.trading_mode": "live"}, {"ai.provider": "gemini"},
    {"ai.min_confidence": 1.5}, {"ai.enabled": "yes"}, {"ai.daily_call_budget": 1.5},
    {"ai.daily_call_budget": -1}, {},
])
def test_settings_rejects_bad_or_forbidden_changes(wired, config, payload):
    c, _, _ = wired
    assert c.patch("/api/settings", json=payload).status_code == 422
    assert config.mode.trading_mode == "dry_run"


def test_settings_partial_failure_changes_nothing(wired, config):
    c, _, _ = wired
    before = config.ai.min_confidence
    assert c.patch("/api/settings", json={"ai.min_confidence": 0.5, "nope": 1}).status_code == 422
    assert config.ai.min_confidence == before


def test_overrides_applied_at_startup(db, config):
    from app.settings import apply_overrides
    with db.session() as s:
        repo.set_override(s, "ai.enabled", False, "owner")
        repo.set_override(s, "bogus.key", 1, "owner")
        repo.set_override(s, "trading.min_edge", 7, "owner")   # out of range: ignored
    assert apply_overrides(config, db) == {"ai.enabled": False}
    assert config.ai.enabled is False


async def test_ai_toggle_off_via_settings_makes_everything_unverified(wired, config, db):
    c, state, pair = wired
    await state.scanner.scan_once()
    assert state.cross_platform["cross_opportunities"][0]["actionable"]
    res = c.patch("/api/settings", json={"ai.enabled": False})
    assert res.status_code == 200
    assert pair.verification_status == "unverified"
    opp = state.cross_platform["cross_opportunities"][0]
    assert opp["actionable"] is False and opp["verification_status"] == "unverified"
    with db.session() as s:
        assert any(a.event == "config_change" and a.detail["key"] == "ai.enabled"
                   for a in repo.list_audit(s))


def test_ai_usage_endpoint(wired):
    c, _, _ = wired
    body = c.get("/api/ai/usage").json()
    assert body["calls_today"] == 0 and body["call_budget"] == 400 and body["exhausted"] is False
    assert body["ai"]["provider"] == "fake"


def test_state_exposes_ai_and_agent_state(wired):
    c, _, _ = wired
    s = c.get("/api/state").json()
    assert s["ai"]["enabled"] is True and "agent_state" in s and s["pairs"]["total"] == 1
