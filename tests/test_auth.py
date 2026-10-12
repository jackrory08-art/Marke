import re

import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, MAX_FAILURES
from app.create_user import CreateUserError, create_user
from app.db import init_database
from dashboard.server import create_app
from tests.conftest import ORIGIN, OWNER, OWNER_PASSWORD, all_routes

PUBLIC = {"/login", "/api/auth/login", "/healthz"}


def login(client, password=OWNER_PASSWORD, username=OWNER, **kw):
    return client.post("/api/auth/login",
                       json={"username": username, "password": password}, **kw)


def test_login_sets_cookie_flags(config, db, clock, state, owner):
    config.server.cookie_secure = True
    app = create_app(config, db=db, clock=clock, state=state)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as c:
        res = login(c)
    assert res.status_code == 204
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    low = cookie.lower()
    assert "httponly" in low and "secure" in low and "samesite=strict" in low and "path=/" in low


def test_bad_password_is_generic_401(client, owner):
    bad_pw = login(client, password="wrong password!!")
    bad_user = login(client, username="nobody")
    assert bad_pw.status_code == bad_user.status_code == 401
    assert bad_pw.json() == bad_user.json()


def test_lockout_after_failures_even_with_correct_password(client, owner):
    for _ in range(MAX_FAILURES):
        res = login(client, password="wrong password!!")
    assert res.status_code == 429 and "retry-after" in res.headers
    res = login(client)  # correct password, still locked
    assert res.status_code == 429


def test_lockout_expires(client, owner, clock):
    for _ in range(MAX_FAILURES):
        login(client, password="wrong password!!")
    clock.advance(minutes=16)
    assert login(client).status_code == 204


def test_unknown_user_lockout_matches_real_user(client):
    for _ in range(MAX_FAILURES):
        res = login(client, username="ghost", password="x" * 12)
    assert res.status_code == 429


def test_per_ip_limit(client, owner):
    codes = [login(client, username=f"user{i}", password="x" * 12).status_code for i in range(25)]
    assert 429 in codes[20:]


def test_logout_invalidates_session(logged_in_client):
    c = logged_in_client
    assert c.get("/api/state").status_code == 200
    assert c.post("/api/auth/logout").status_code == 204
    c.cookies.clear()
    assert c.get("/api/state").status_code == 401


def test_logout_session_dead_even_if_cookie_replayed(logged_in_client):
    c = logged_in_client
    cookie = c.cookies.get(COOKIE_NAME)
    c.post("/api/auth/logout")
    c.cookies.set(COOKIE_NAME, cookie)
    assert c.get("/api/state").status_code == 401


def test_idle_expiry(logged_in_client, clock):
    clock.advance(minutes=119)
    assert logged_in_client.get("/api/state").status_code == 200
    clock.advance(minutes=121)
    assert logged_in_client.get("/api/state").status_code == 401


def test_absolute_expiry(logged_in_client, clock):
    # Stay active (under the idle limit) but cross the 12h absolute limit.
    for _ in range(11):
        clock.advance(hours=1)
        assert logged_in_client.get("/api/state").status_code == 200
    clock.advance(hours=1, minutes=1)
    assert logged_in_client.get("/api/state").status_code == 401


def test_session_rotates_on_login(client, owner):
    login(client)
    first = client.cookies.get(COOKIE_NAME)
    login(client)
    assert client.cookies.get(COOKIE_NAME) != first


def test_csrf_missing_or_wrong_is_403(logged_in_client):
    c = logged_in_client
    token = c.headers.pop("X-CSRF-Token")
    assert c.post("/api/auth/logout").status_code == 403
    assert c.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.post("/api/auth/logout", headers={"X-CSRF-Token": token}).status_code == 204


def test_foreign_origin_is_403(logged_in_client):
    c = logged_in_client
    assert c.post("/api/auth/logout", headers={"Origin": "http://evil.example"}).status_code == 403
    assert login(c, headers={"Origin": "http://evil.example"}).status_code == 403


def test_missing_origin_rejected(app, owner):
    with TestClient(app, base_url=ORIGIN) as c:  # no Origin header
        assert login(c).status_code == 403


def test_referer_fallback(app, owner):
    with TestClient(app, base_url=ORIGIN) as c:
        assert login(c, headers={"Referer": ORIGIN + "/login"}).status_code == 204


def test_every_route_requires_auth(app):
    checked = 0
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as c:
        for path, methods in all_routes(app):
            if path in PUBLIC or path.startswith("/static/") or "WEBSOCKET" in methods:
                continue
            url = re.sub(r"\{[^}]+\}", "x", path)
            for m in methods - {"HEAD", "OPTIONS"}:
                res = c.request(m, url, headers={"Origin": ORIGIN})
                assert res.status_code in (401, 303), (m, path, res.status_code)
                checked += 1
    assert checked >= 5


def test_unknown_and_static_paths_denied_when_anonymous(client):
    for p in ("/static/js/legacy.js", "/static/index.html", "/nope", "/openapi.json", "/docs"):
        res = client.get(p, follow_redirects=False)
        assert res.status_code in (303, 401), p


def test_public_paths(client):
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/login").status_code == 200
    assert client.get("/static/login.js").status_code == 200
    assert client.get("/static/css/login.css").status_code == 200


def test_path_traversal_blocked(logged_in_client):
    res = logged_in_client.get("/static/..%2f..%2fconfig.yaml")
    assert res.status_code == 404


def test_security_headers(client):
    res = client.get("/login")
    assert "default-src 'self'" in res.headers["content-security-policy"]
    assert "script-src 'self'" in res.headers["content-security-policy"]
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert res.headers["x-frame-options"] == "DENY"
    assert "permissions-policy" in res.headers
    assert client.get("/api/state").headers["cache-control"] == "no-store"


def test_no_cors_for_foreign_origin(client):
    res = client.get("/healthz", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_untrusted_host_rejected(app):
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/healthz").status_code == 400


def test_me_returns_csrf(logged_in_client):
    body = logged_in_client.get("/api/auth/me").json()
    assert body["username"] == OWNER and body["csrf_token"] and body["expires_at"]


def test_audit_events_written(logged_in_client):
    logged_in_client.post("/api/auth/logout")
    logged_in_client.cookies.clear()
    # log back in to read the audit log
    login(logged_in_client)
    events = logged_in_client.get("/api/audit").json()["events"]
    kinds = {e["event"] for e in events}
    assert {"login_success", "logout", "user_created"} <= kinds


def test_create_user_rules(db):
    with pytest.raises(CreateUserError):
        create_user(db, "a", "short")
    create_user(db, "a", "a-long-enough-pw")
    with pytest.raises(CreateUserError):
        create_user(db, "b", "another-long-pw!")
    create_user(db, "b", "another-long-pw!", add=True)


def test_password_stored_hashed(db, owner):
    from app import repo
    with db.session() as s:
        u = repo.get_user_by_username(s, OWNER)
        assert u.password_hash.startswith("$argon2id$")


def test_bootstrap_owner_only_when_empty_and_configured(db, monkeypatch, caplog):
    from app import repo
    from app.create_user import bootstrap_owner_from_env
    monkeypatch.delenv("MARKE_BOOTSTRAP_USER", raising=False)
    monkeypatch.delenv("MARKE_BOOTSTRAP_PASSWORD", raising=False)
    assert bootstrap_owner_from_env(db) is False                       # nothing configured

    monkeypatch.setenv("MARKE_BOOTSTRAP_USER", "Boss")
    monkeypatch.setenv("MARKE_BOOTSTRAP_PASSWORD", "short")
    assert bootstrap_owner_from_env(db) is False                       # weak password refused
    with db.session() as s:
        assert repo.count_users(s) == 0

    monkeypatch.setenv("MARKE_BOOTSTRAP_PASSWORD", "a-long-enough-secret")
    with caplog.at_level("WARNING"):
        assert bootstrap_owner_from_env(db) is True
    assert "a-long-enough-secret" not in caplog.text
    with db.session() as s:
        assert repo.get_user_by_username(s, "boss") is not None

    monkeypatch.setenv("MARKE_BOOTSTRAP_USER", "intruder")             # users exist: never adds more
    assert bootstrap_owner_from_env(db) is False
    with db.session() as s:
        assert repo.count_users(s) == 1


def test_bootstrapped_user_can_log_in(client, db, monkeypatch):
    from app.create_user import bootstrap_owner_from_env
    monkeypatch.setenv("MARKE_BOOTSTRAP_USER", "boss")
    monkeypatch.setenv("MARKE_BOOTSTRAP_PASSWORD", "a-long-enough-secret")
    bootstrap_owner_from_env(db)
    assert login(client, "a-long-enough-secret", "boss").status_code == 204
