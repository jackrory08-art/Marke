"""Security middleware: headers, trusted hosts and the deny-by-default auth gate."""

import json
import logging
from http.cookies import SimpleCookie
from typing import Optional

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth import COOKIE_NAME, AuthService
from app.config import ServerConfig

logger = logging.getLogger(__name__)

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

# The only paths reachable without a session. Everything else is denied.
PUBLIC_EXACT = {"/login", "/api/auth/login", "/healthz"}


def is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    if path.startswith("/static/css/"):
        return True
    if path.startswith("/static/login."):
        return True
    return False


def parse_cookie(header: Optional[str], name: str = COOKIE_NAME) -> Optional[str]:
    if not header:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(header)
    except Exception:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


class SecurityHeadersMiddleware:
    """Adds CSP and friends to every HTTP response."""

    def __init__(self, app: ASGIApp, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                extra = {
                    b"content-security-policy": CSP,
                    b"x-content-type-options": "nosniff",
                    b"referrer-policy": "no-referrer",
                    b"x-frame-options": "DENY",
                    b"permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
                }
                if path.startswith("/api") or path in ("/login", "/"):
                    extra[b"cache-control"] = "no-store"
                if self.hsts:
                    extra[b"strict-transport-security"] = "max-age=31536000; includeSubDomains"
                present = {k.lower() for k, _ in headers}
                for k, v in extra.items():
                    if k not in present:
                        headers.append((k, v.encode()))
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AuthGateMiddleware:
    """Deny by default.

    Any HTTP request outside the public allowlist needs a live session.
    Unauthenticated ``/api`` calls get a 401 JSON body, pages get a 303 to
    ``/login``. The resolved session is stored in ``scope["state"]`` for the
    route dependencies. WebSockets are checked in the endpoint itself (before
    ``accept``).
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        auth: AuthService = scope["app"].state.auth
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        token = parse_cookie(headers.get(b"cookie", b"").decode("latin-1"))
        info = await run_in_threadpool(auth.validate, token) if token else None
        scope.setdefault("state", {})["session"] = info
        scope["state"]["session_token"] = token

        if info is None and not is_public_path(path):
            if path.startswith("/api"):
                body = json.dumps({"detail": "Not authenticated"}).encode()
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
            else:
                await send({"type": "http.response.start", "status": 303, "headers": [
                    (b"location", b"/login"), (b"content-length", b"0")]})
                await send({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send)


def install_security(app, server: ServerConfig) -> None:
    """Install middleware. Order (outermost first): headers, hosts, auth gate."""
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(AuthGateMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(server.allowed_hosts))
    app.add_middleware(SecurityHeadersMiddleware, hsts=server.hsts)
    if server.allowed_origins:
        from starlette.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware, allow_origins=list(server.allowed_origins),
            allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"])
