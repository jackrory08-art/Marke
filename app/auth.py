"""Authentication: argon2id passwords, DB-backed sessions, lockout and rate limits.

Session tokens are random and live only in the cookie; the database stores a
hash of the token. Failures are always reported with a generic message.
"""

import hashlib
import hmac
import logging
import os
import secrets
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app import repo
from app.clock import utcnow
from app.config import ServerConfig
from app.db import Database

logger = logging.getLogger(__name__)

COOKIE_NAME = "marke_session"
MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
IP_WINDOW = timedelta(minutes=15)
IP_MAX_ATTEMPTS = 20
MIN_PASSWORD_LENGTH = 12
# Only refresh last_seen_at this often, to avoid a DB write per request.
TOUCH_INTERVAL = timedelta(seconds=30)

_hasher = PasswordHasher()
# Verified against when the username is unknown so timing matches a real user.
_DUMMY_HASH = _hasher.hash("marke-dummy-password-for-timing")


class AuthError(Exception):
    """Login failed. ``status`` is 401 (bad credentials) or 429 (throttled)."""

    def __init__(self, status: int = 401, retry_after: Optional[int] = None):
        super().__init__("Invalid credentials" if status == 401 else "Too many attempts")
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class SessionInfo:
    session_id: str      # hash of the token
    user_id: int
    username: str
    csrf_token: str
    expires_at: datetime
    created_at: datetime


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def validate_password_strength(password: str) -> Optional[str]:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


class AuthService:
    def __init__(
        self, db: Database, server: ServerConfig,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.db = db
        self.server = server
        self.clock = clock
        self._lock = threading.Lock()
        self._ip_attempts: dict[str, deque] = defaultdict(deque)
        # Unknown usernames have no row to lock, so track them in memory to
        # make lockout behaviour indistinguishable from a real account.
        self._unknown_failures: dict[str, tuple[int, Optional[datetime]]] = {}
        self._secret = os.environ.get("MARKE_SESSION_SECRET", "")

    # --------------------------------------------------------------- tokens
    def token_id(self, token: str) -> str:
        if self._secret:
            return hmac.new(self._secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        return hashlib.sha256(token.encode()).hexdigest()

    # --------------------------------------------------------------- limits
    def _ip_check(self, ip: str, now: datetime) -> None:
        with self._lock:
            q = self._ip_attempts[ip]
            while q and q[0] <= now - IP_WINDOW:
                q.popleft()
            if len(q) >= IP_MAX_ATTEMPTS:
                retry = int((q[0] + IP_WINDOW - now).total_seconds()) + 1
                raise AuthError(429, max(retry, 1))
            q.append(now)

    # ---------------------------------------------------------------- login
    def login(
        self, username: str, password: str, ip: str = "", user_agent: str = "",
        existing_token: Optional[str] = None,
    ) -> tuple[str, SessionInfo]:
        """Return ``(token, SessionInfo)`` or raise :class:`AuthError`."""
        now = self.clock()
        username = (username or "").strip().lower()
        password = password or ""
        self._ip_check(ip or "?", now)

        with self.db.session() as s:
            user = repo.get_user_by_username(s, username) if username else None

            if user is not None and user.locked_until and user.locked_until > now:
                retry = int((user.locked_until - now).total_seconds()) + 1
                repo.add_audit(s, "login_failure", user_id=user.id, ip=ip,
                               detail={"reason": "locked"}, at=now)
                s.commit()
                raise AuthError(429, retry)
            if user is None:
                state = self._unknown_failures.get(username)
                if state and state[1] and state[1] > now:
                    raise AuthError(429, int((state[1] - now).total_seconds()) + 1)

            ok = self._verify(user, password)
            if not ok or user is None or not user.is_active:
                self._record_failure(s, user, username, ip, now)
                s.commit()
                locked = user.locked_until if user is not None else \
                    (self._unknown_failures.get(username) or (0, None))[1]
                if locked and locked > now:
                    raise AuthError(429, int((locked - now).total_seconds()) + 1)
                raise AuthError(401)

            # Success
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            if _hasher.check_needs_rehash(user.password_hash):
                user.password_hash = _hasher.hash(password)
            if existing_token:  # rotate: never reuse a pre-login session
                repo.delete_session_row(s, self.token_id(existing_token))
            repo.purge_expired_sessions(s, now)
            token = secrets.token_urlsafe(32)
            info = self._create_session(s, user, token, ip, user_agent, now)
            repo.add_audit(s, "login_success", user_id=user.id, ip=ip, at=now)
            self._unknown_failures.pop(username, None)
        return token, info

    @staticmethod
    def _verify(user, password: str) -> bool:
        stored = user.password_hash if user is not None else _DUMMY_HASH
        try:
            result = _hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False
        return bool(result) and user is not None

    def _record_failure(self, s, user, username: str, ip: str, now: datetime) -> None:
        if user is not None:
            user.failed_login_count += 1
            repo.add_audit(s, "login_failure", user_id=user.id, ip=ip, at=now,
                           detail={"count": user.failed_login_count})
            if user.failed_login_count >= MAX_FAILURES:
                user.locked_until = now + LOCKOUT
                user.failed_login_count = 0
                repo.add_audit(s, "lockout", user_id=user.id, ip=ip, at=now)
        else:
            count, _ = self._unknown_failures.get(username, (0, None))
            count += 1
            locked = None
            if count >= MAX_FAILURES:
                locked, count = now + LOCKOUT, 0
            if len(self._unknown_failures) > 5000:
                self._unknown_failures.clear()
            self._unknown_failures[username] = (count, locked)
            repo.add_audit(s, "login_failure", ip=ip, at=now, detail={"unknown_user": True})

    def _create_session(self, s, user, token: str, ip: str, ua: str, now: datetime) -> SessionInfo:
        expires = now + timedelta(hours=self.server.session_absolute_hours)
        csrf = secrets.token_urlsafe(32)
        row = repo.create_session_row(
            s, id=self.token_id(token), user_id=user.id, csrf_token=csrf,
            created_at=now, last_seen_at=now, expires_at=expires,
            ip=(ip or "")[:64], user_agent=(ua or "")[:255])
        return SessionInfo(row.id, user.id, user.username, csrf, expires, now)

    # ------------------------------------------------------------- sessions
    def validate(self, token: Optional[str]) -> Optional[SessionInfo]:
        """Resolve a cookie token to a live session, enforcing idle/absolute expiry."""
        if not token:
            return None
        now = self.clock()
        sid = self.token_id(token)
        with self.db.session() as s:
            row = repo.get_session_row(s, sid)
            if row is None:
                return None
            idle = timedelta(minutes=self.server.session_idle_minutes)
            if row.expires_at <= now or row.last_seen_at + idle <= now:
                repo.add_audit(s, "session_expired", user_id=row.user_id, ip=row.ip, at=now)
                repo.delete_session_row(s, sid)
                return None
            user = repo.get_user(s, row.user_id)
            if user is None or not user.is_active:
                repo.delete_session_row(s, sid)
                return None
            if now - row.last_seen_at >= TOUCH_INTERVAL:
                row.last_seen_at = now
            return SessionInfo(sid, user.id, user.username, row.csrf_token,
                               row.expires_at, row.created_at)

    def logout(self, token: Optional[str], ip: str = "") -> Optional[str]:
        """Delete the session; returns its id (for closing sockets)."""
        if not token:
            return None
        sid = self.token_id(token)
        with self.db.session() as s:
            row = repo.get_session_row(s, sid)
            if row is None:
                return None
            repo.add_audit(s, "logout", user_id=row.user_id, ip=ip, at=self.clock())
            repo.delete_session_row(s, sid)
        return sid
