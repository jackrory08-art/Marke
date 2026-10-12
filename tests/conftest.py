"""Shared fixtures: temp SQLite DB, app, owner user, logged-in client, fake AI provider."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.create_user import create_user  # noqa: E402
from app.db import init_database  # noqa: E402
from dashboard.server import create_app  # noqa: E402
from dashboard.state import DashboardState  # noqa: E402
from utils.config_loader import get_default_config  # noqa: E402

OWNER = "owner"
OWNER_PASSWORD = "correct horse battery"
ORIGIN = "http://testserver"


class FakeClock:
    """Injectable clock for session expiry tests."""

    def __init__(self):
        self.now = datetime(2026, 1, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def config(tmp_path):
    cfg = get_default_config()
    cfg.database.url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg.server.cookie_secure = False
    cfg.server.allowed_hosts = ["testserver", "127.0.0.1", "localhost"]
    cfg.ai.provider = "mock"
    return cfg


@pytest.fixture
def db(config):
    database = init_database(config.database.url, auto_migrate=True)
    yield database
    database.dispose()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state():
    return DashboardState()


@pytest.fixture
def app(config, db, clock, state):
    return create_app(config, db=db, clock=clock, state=state)


@pytest.fixture
def owner(db):
    create_user(db, OWNER, OWNER_PASSWORD)
    return OWNER


@pytest.fixture
def client(app):
    """Unauthenticated client that sends a same-origin Origin header."""
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as c:
        yield c


@pytest.fixture
def logged_in_client(client, owner):
    res = client.post("/api/auth/login", json={"username": OWNER, "password": OWNER_PASSWORD})
    assert res.status_code == 204
    me = client.get("/api/auth/me").json()
    client.headers["X-CSRF-Token"] = me["csrf_token"]
    return client


def all_routes(app):
    """Flatten app.routes (FastAPI nests included routers) to (path, methods)."""
    out = []
    for r in app.routes:
        if hasattr(r, "original_router"):
            out.extend((x.path, getattr(x, "methods", None) or {"WEBSOCKET"})
                       for x in r.original_router.routes)
        else:
            out.append((r.path, getattr(r, "methods", None) or {"WEBSOCKET"}))
    return out
