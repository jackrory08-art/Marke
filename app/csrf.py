"""CSRF defences: Origin/Referer check plus a per-session synchronizer token."""

import hmac
from typing import Iterable, Optional
from urllib.parse import urlsplit

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(value: str) -> Optional[str]:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def origin_allowed(
    origin: Optional[str], referer: Optional[str], host: Optional[str],
    allowed_origins: Iterable[str] = (),
) -> bool:
    """True if the request's Origin (falling back to Referer) is same-host or allow-listed.

    A request carrying neither header is rejected: browsers always send
    ``Origin`` on unsafe methods and WebSocket handshakes.
    """
    candidate = origin or referer
    if not candidate or candidate == "null":
        return False
    found = _origin_of(candidate)
    if found is None:
        return False
    allowed = {o.rstrip("/").lower() for o in allowed_origins}
    if found in allowed:
        return True
    netloc = urlsplit(found).netloc
    return bool(host) and netloc == host.lower()


def csrf_token_valid(expected: str, supplied: Optional[str]) -> bool:
    return bool(supplied) and bool(expected) and hmac.compare_digest(expected, supplied)
