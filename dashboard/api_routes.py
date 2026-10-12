"""Protected JSON API. Every route here requires a session (``require_user``)."""

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app import repo
from dashboard.auth_routes import require_csrf, require_user
from dashboard.state import dashboard_state as _default_state

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
