"""Time helpers. All timestamps in the database are naive UTC."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current time as a naive UTC datetime (what the database stores)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_day(now: datetime | None = None) -> str:
    """UTC calendar day as ``YYYY-MM-DD``."""
    return (now or utcnow()).strftime("%Y-%m-%d")
