"""Login, logout and ``/api/auth/me``."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.auth import COOKIE_NAME, AuthError, AuthService, SessionInfo
from app.csrf import UNSAFE_METHODS, csrf_token_valid, origin_allowed

router = APIRouter()


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def check_origin(request: Request) -> None:
    server = request.app.state.config.server
    if not origin_allowed(
        request.headers.get("origin"), request.headers.get("referer"),
        request.headers.get("host"), server.allowed_origins,
    ):
        raise HTTPException(403, "Forbidden origin")


def require_user(request: Request) -> SessionInfo:
    """Dependency: the logged-in session (the gate middleware already resolved it)."""
    info: Optional[SessionInfo] = request.scope.get("state", {}).get("session")
    if info is None:
        raise HTTPException(401, "Not authenticated")
    return info


def require_csrf(request: Request, user: SessionInfo = Depends(require_user)) -> SessionInfo:
    """Dependency for protected routes: origin + synchronizer token on unsafe methods."""
    if request.method in UNSAFE_METHODS:
        check_origin(request)
        if not csrf_token_valid(user.csrf_token, request.headers.get("x-csrf-token")):
            raise HTTPException(403, "Invalid CSRF token")
    return user


@router.post("/api/auth/login", status_code=204)
async def login(body: LoginBody, request: Request):
    check_origin(request)
    auth: AuthService = request.app.state.auth
    server = request.app.state.config.server
    try:
        token, info = await run_in_threadpool(
            auth.login, body.username, body.password, client_ip(request),
            request.headers.get("user-agent", ""),
            request.scope["state"].get("session_token"))
    except AuthError as e:
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        raise HTTPException(e.status, str(e), headers=headers)
    resp = Response(status_code=204)
    resp.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=server.cookie_secure,
        samesite="strict", path="/", max_age=server.session_absolute_hours * 3600)
    return resp


@router.post("/api/auth/logout", status_code=204)
async def logout(request: Request, user: SessionInfo = Depends(require_csrf)):
    auth: AuthService = request.app.state.auth
    token = request.scope["state"].get("session_token")
    sid = await run_in_threadpool(auth.logout, token, client_ip(request))
    if sid:
        await request.app.state.dashboard_state.close_session_sockets(sid)
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/api/auth/me")
async def me(user: SessionInfo = Depends(require_user)):
    return {
        "username": user.username,
        "csrf_token": user.csrf_token,
        "expires_at": user.expires_at.isoformat() + "Z",
    }
