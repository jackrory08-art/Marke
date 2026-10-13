"""
Dashboard Server
=================

FastAPI application factory. State lives in :mod:`dashboard.state`,
middleware in :mod:`dashboard.security`, routes in ``auth_routes``,
``api_routes`` and ``ws``.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.requests import Request

from app.auth import AuthService
from app.clock import utcnow
from app.db import Database, init_database
from app.logbuffer import RingBufferHandler
from dashboard import api_routes, auth_routes, ws
from dashboard.security import install_security, is_public_path
from dashboard.state import DashboardState, dashboard_state

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

__all__ = ["create_app", "dashboard_state", "DashboardState"]


def _static_file(rel: str) -> Optional[Path]:
    """Resolve a path under static/ without allowing traversal."""
    candidate = (STATIC_DIR / rel).resolve()
    try:
        candidate.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def create_app(
    config=None,
    *,
    db: Optional[Database] = None,
    clock: Callable = utcnow,
    state: Optional[DashboardState] = None,
) -> FastAPI:
    """Create the dashboard application."""
    if config is None:
        from utils.config_loader import get_default_config
        config = get_default_config()

    owns_db = db is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if owns_db:
            db.dispose()

    app = FastAPI(
        title="Marke Dashboard", version="2.0.0",
        docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
    )
    if db is None:
        db = init_database(config.database.url, config.database.auto_migrate)

    app.state.config = config
    app.state.db = db
    app.state.auth = AuthService(db, config.server, clock=clock)
    app.state.dashboard_state = state or dashboard_state
    app.state.ws_heartbeat_s = 30.0
    app.state.dashboard_state.paused = bool(getattr(config.mode, "paused", False))

    if app.state.dashboard_state.log_buffer is None:
        handler = RingBufferHandler()
        logging.getLogger().addHandler(handler)
        app.state.dashboard_state.log_buffer = handler

    install_security(app, config.server)

    app.include_router(auth_routes.router)
    app.include_router(api_routes.router)
    app.include_router(ws.router)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/login")
    async def login_page(request: Request):
        if request.scope["state"].get("session") is not None:
            return RedirectResponse("/", status_code=303)
        page = _static_file("login.html")
        if page is None:
            return PlainTextResponse("Login page missing", status_code=503)
        return FileResponse(page)

    @app.get("/")
    async def index():
        page = _static_file("index.html")
        if page is None:
            return PlainTextResponse("Dashboard UI not built", status_code=503)
        return FileResponse(page)

    @app.get("/static/{path:path}")
    async def static(path: str):
        # Public vs private is decided by the auth gate; this only serves files.
        f = _static_file(path)
        if f is None:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(f)

    return app


def __getattr__(name: str):
    # Lazy ``from dashboard.server import app`` for backwards compatibility.
    if name == "app":
        global _lazy_app
        try:
            return _lazy_app
        except NameError:
            _lazy_app = create_app()
            return _lazy_app
    raise AttributeError(name)
