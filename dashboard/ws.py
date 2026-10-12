"""Authenticated WebSocket endpoint."""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.csrf import origin_allowed
from dashboard.security import parse_cookie
from dashboard.state import make_event

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    app = websocket.app
    auth = app.state.auth
    state = app.state.dashboard_state
    config = app.state.config

    # Check Origin and the session cookie *before* accepting the handshake.
    if not origin_allowed(
        websocket.headers.get("origin"), None, websocket.headers.get("host"),
        config.server.allowed_origins,
    ):
        await websocket.close(code=4403)
        return
    token = parse_cookie(websocket.headers.get("cookie"))
    info = await run_in_threadpool(auth.validate, token)
    if info is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    state.register(websocket, info.session_id)
    heartbeat = getattr(app.state, "ws_heartbeat_s", 30.0)

    try:
        await websocket.send_text(json.dumps(make_event("initial", state.to_dict()), default=str))
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=heartbeat)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await websocket.send_text(json.dumps(make_event("pong")))
            except asyncio.TimeoutError:
                # Heartbeat: re-check the session, tell the client if it ended.
                if await run_in_threadpool(auth.validate, token) is None:
                    await websocket.send_text(json.dumps(make_event("session_expired")))
                    await websocket.close(code=4401)
                    return
                await websocket.send_text(json.dumps(make_event("heartbeat")))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        state.unregister(websocket)
