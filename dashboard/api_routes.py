"""Protected JSON API. Every route here requires a session (``require_user``)."""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app import repo
from app.auth import SessionInfo
from app.settings import SettingError, apply, coerce, describe, get_value
from core.pair_store import pair_to_public
from dashboard.auth_routes import require_csrf, require_user

router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf)])


def _state(request: Request):
    return request.app.state.dashboard_state


@router.get("/state")
async def get_state(request: Request):
    return _state(request).to_dict()


@router.get("/markets")
async def get_markets(request: Request):
    return {"markets": _state(request).markets}


@router.get("/portfolio")
async def get_portfolio(request: Request):
    return _state(request).portfolio


@router.get("/risk")
async def get_risk(request: Request):
    return _state(request).risk


@router.get("/timing")
async def get_timing(request: Request):
    return _state(request).timing


@router.get("/audit")
async def get_audit(
    request: Request, limit: int = Query(100, ge=1, le=500), before: int | None = None,
):
    db = request.app.state.db

    def load():
        with db.session() as s:
            return [{
                "id": r.id, "at": r.at.isoformat() + "Z", "event": r.event,
                "user_id": r.user_id, "ip": r.ip, "detail": r.detail,
            } for r in repo.list_audit(s, limit, before)]
    return {"events": await run_in_threadpool(load)}


@router.get("/logs")
async def get_logs(request: Request, limit: int = Query(200, ge=1, le=1000), level: str | None = None):
    buf = _state(request).log_buffer
    return {"logs": buf.recent(limit, level) if buf else []}


# ----------------------------------------------------------- opportunities
def _bundle_to_public(state, opp: dict) -> dict:
    market_id = opp.get("market_id", "")
    market = state.markets.get(market_id, {})
    return {
        "id": f"bundle|{market_id}|{opp.get('type', '')}",
        "kind": "bundle",
        "pair_id": None,
        "platforms": ["polymarket"],
        "title_a": market.get("question", market_id),
        "title_b": "",
        "market_a_id": market_id,
        "market_b_id": None,
        "net_edge": opp.get("edge", 0.0),
        "gross_edge": opp.get("edge", 0.0),
        "suggested_size": opp.get("suggested_size"),
        "fees": {},
        "depth": None,
        "verification_status": "n/a",
        "actionable": True,
        "manual_trade": False,
        "quality_score": None,
        "analysis": None,
        "bundle_type": opp.get("type"),
        "detected_at": opp.get("timestamp"),
    }


def combined_opportunities(state) -> list[dict]:
    items = list(state.cross_platform.get("cross_opportunities", []))
    bundles: dict[str, dict] = {}
    for opp in state.opportunities[-100:]:
        pub = _bundle_to_public(state, opp)
        bundles[pub["id"]] = pub  # latest per market/type
    items.extend(bundles.values())
    items.sort(key=lambda o: o.get("net_edge") or 0.0, reverse=True)
    return items


@router.get("/opportunities/history")
async def opportunity_history(
    request: Request, limit: int = Query(100, ge=1, le=500), kind: str | None = None,
):
    db = request.app.state.db

    def load():
        with db.session() as s:
            return [{
                "id": r.opportunity_key, "kind": r.kind, "pair_id": r.pair_key,
                "platforms": r.platforms.split("|"), "market_a_id": r.market_a_id,
                "market_b_id": r.market_b_id, "net_edge": r.net_edge,
                "gross_edge": r.gross_edge, "max_net_edge": r.max_net_edge,
                "fees": r.fees, "depth": r.depth,
                "verification_status": r.verification_status, "actionable": r.actionable,
                "first_seen_at": r.first_seen_at.isoformat() + "Z",
                "last_seen_at": r.last_seen_at.isoformat() + "Z",
                "seen_count": r.seen_count,
            } for r in repo.list_history(s, limit, kind)]
    return {"history": await run_in_threadpool(load)}


@router.get("/opportunities")
async def list_opportunities(
    request: Request, status: str | None = None, platform: str | None = None,
    actionable: bool | None = None,
):
    items = combined_opportunities(_state(request))
    if status:
        items = [o for o in items if o.get("verification_status") == status]
    if platform:
        items = [o for o in items if platform in o.get("platforms", [])]
    if actionable is not None:
        items = [o for o in items if bool(o.get("actionable")) == actionable]
    return {"opportunities": items, "count": len(items)}


@router.get("/opportunities/{opportunity_id:path}")
async def get_opportunity(opportunity_id: str, request: Request):
    for o in combined_opportunities(_state(request)):
        if o["id"] == opportunity_id:
            return o
    raise HTTPException(404, "Opportunity not found")


# -------------------------------------------------------------------- pairs
def _store(request: Request):
    store = _state(request).pair_store
    if store is None:
        raise HTTPException(503, "Cross-platform matching is not running")
    return store


@router.get("/pairs")
async def list_pairs(request: Request, status: str | None = None, platform: str | None = None):
    store = _store(request)
    pairs = sorted(store.list(status, platform), key=lambda p: p.similarity_score, reverse=True)
    return {"pairs": [pair_to_public(p) for p in pairs], "counts": store.counts()}


async def _set_dismissed(request: Request, pair_id: str, dismissed: bool, user) -> dict:
    store = _store(request)
    pair = store.get(pair_id)
    if pair is None:
        raise HTTPException(404, "Pair not found")
    db = request.app.state.db

    def write():
        with db.session() as s:
            if dismissed:
                repo.dismiss_pair(s, pair_id, user.user_id)
            else:
                repo.undismiss_pair(s, pair_id)
    await run_in_threadpool(write)
    store.set_dismissed(pair_id, dismissed)
    state = _state(request)
    if state.scanner is not None:
        if dismissed:
            state.scanner.on_pair_dismissed(pair_id)
    state.emit("pair_dismissed", {"pair_id": pair_id, "dismissed": dismissed})
    return pair_to_public(pair)


@router.post("/pairs/{pair_id}/dismiss")
async def dismiss_pair(pair_id: str, request: Request, user: SessionInfo = Depends(require_user)):
    return await _set_dismissed(request, pair_id, True, user)


@router.delete("/pairs/{pair_id}/dismiss")
async def undismiss_pair(pair_id: str, request: Request, user: SessionInfo = Depends(require_user)):
    return await _set_dismissed(request, pair_id, False, user)


@router.post("/pairs/{pair_id}/reverify", status_code=202)
async def reverify_pair(pair_id: str, request: Request):
    store = _store(request)
    state = _state(request)
    pair = store.get(pair_id)
    if pair is None:
        raise HTTPException(404, "Pair not found")
    if state.ai is None:
        raise HTTPException(503, "AI verification is not running")
    store.set_verification(pair_id, "pending", {})
    state.ai.queue.enqueue(pair_id, force=True)
    return pair_to_public(pair)


# ----------------------------------------------------------------- settings
@router.get("/settings")
async def get_settings(request: Request):
    return describe(request.app.state.config)


@router.patch("/settings")
async def patch_settings(
    request: Request, changes: dict[str, Any] = Body(...), user: SessionInfo = Depends(require_user),
):
    config = request.app.state.config
    db = request.app.state.db
    state = _state(request)
    if not changes:
        raise HTTPException(422, "No changes supplied")
    # Validate everything first so a bad key never leaves a half-applied change.
    try:
        coerced = {k: coerce(k, v) for k, v in changes.items()}
    except SettingError as e:
        raise HTTPException(422, str(e))
    old = {k: get_value(config, k) for k in coerced}

    for key, value in coerced.items():
        apply(config, key, value)

    def persist():
        with db.session() as s:
            for key, value in coerced.items():
                repo.set_override(s, key, value, user.username)
                repo.add_audit(s, "config_change", user_id=user.user_id,
                               ip=request.client.host if request.client else "",
                               detail={"key": key, "old": old[key], "new": value})
    await run_in_threadpool(persist)

    if "mode.paused" in coerced:
        state.set_paused(coerced["mode.paused"])
    for key, value in coerced.items():
        state.emit("config_changed", {"key": key, "value": value, "by": user.username})
        hook = state.setting_hooks.get(key)
        if hook is not None:
            await hook(value)
    return describe(config)


# ----------------------------------------------------------------------- ai
@router.get("/ai/usage")
async def ai_usage(request: Request):
    state = _state(request)
    config = request.app.state.config
    if state.ai is not None:
        status = await state.ai.runner.budget_status()
    else:
        db = request.app.state.db

        def load():
            with db.session() as s:
                return repo.get_usage_today(s)
        usage = await run_in_threadpool(load)
        status = {"calls_today": usage["calls"], "call_budget": config.ai.daily_call_budget,
                  "cost_today": usage["cost_usd"], "cost_budget": config.ai.daily_cost_budget_usd,
                  "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                  "exhausted": usage["calls"] >= config.ai.daily_call_budget}
    status["ai"] = state.ai.status() if state.ai else {
        "enabled": config.ai.enabled, "provider": config.ai.provider,
        "model": config.ai.model, "mock": config.ai.provider == "mock"}
    return status
