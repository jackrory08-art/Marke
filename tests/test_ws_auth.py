import pytest
from starlette.websockets import WebSocketDisconnect

from app.auth import COOKIE_NAME
from tests.conftest import ORIGIN, OWNER, OWNER_PASSWORD


def _login_cookie(client):
    client.post("/api/auth/login", json={"username": OWNER, "password": OWNER_PASSWORD})
    return client.cookies.get(COOKIE_NAME)


def test_no_cookie_rejected(client):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws", headers={"Origin": ORIGIN}):
            pass
    assert e.value.code == 4401


def test_bad_origin_rejected(client, owner):
    cookie = _login_cookie(client)
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(
            "/ws", headers={"Origin": "http://evil.example", "Cookie": f"{COOKIE_NAME}={cookie}"}
        ):
            pass
    assert e.value.code == 4403


def test_missing_origin_rejected(client, owner):
    cookie = _login_cookie(client)
    client.headers.pop("Origin", None)
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws", headers={"Cookie": f"{COOKIE_NAME}={cookie}"}):
            pass
    assert e.value.code == 4403


def test_valid_session_gets_initial(logged_in_client):
    with logged_in_client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "initial"
    assert {"type", "ts", "data"} <= set(msg)


def test_expired_session_closed_with_4401(app, logged_in_client, clock):
    app.state.ws_heartbeat_s = 0.2
    with logged_in_client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "initial"
        clock.advance(hours=3)  # past the idle limit
        assert ws.receive_json()["type"] == "session_expired"
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 4401


def test_logout_closes_socket(logged_in_client):
    with logged_in_client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "initial"
        assert logged_in_client.post("/api/auth/logout").status_code == 204
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 4401
