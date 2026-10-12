"""Small repository functions over the ORM models.

Every function takes an open ``Session``; commit/rollback is the caller's
(``Database.session()``).
"""

from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import utc_day, utcnow
from app.models import (
    AIAnalysis, AIUsageDaily, AIVerdict, AuditLog, OpportunityHistory,
    PairDismissal, SessionRow, SettingOverride, User,
)


# --------------------------------------------------------------------- users
def count_users(s: Session) -> int:
    return len(s.execute(select(User.id)).all())


def get_user_by_username(s: Session, username: str) -> Optional[User]:
    return s.execute(
        select(User).where(User.username == username.strip().lower())).scalar_one_or_none()


def get_user(s: Session, user_id: int) -> Optional[User]:
    return s.get(User, user_id)


def create_user(s: Session, username: str, password_hash: str, role: str = "owner") -> User:
    user = User(username=username.strip().lower(), password_hash=password_hash, role=role)
    s.add(user)
    s.flush()
    return user


# ------------------------------------------------------------------ sessions
def create_session_row(s: Session, **fields: Any) -> SessionRow:
    row = SessionRow(**fields)
    s.add(row)
    s.flush()
    return row


def get_session_row(s: Session, session_id: str) -> Optional[SessionRow]:
    return s.get(SessionRow, session_id)


def delete_session_row(s: Session, session_id: str) -> None:
    s.execute(delete(SessionRow).where(SessionRow.id == session_id))


def purge_expired_sessions(s: Session, now: datetime) -> int:
    res = s.execute(delete(SessionRow).where(SessionRow.expires_at <= now))
    return res.rowcount or 0


# --------------------------------------------------------------------- audit
def add_audit(
    s: Session, event: str, *, user_id: Optional[int] = None,
    ip: Optional[str] = None, detail: Optional[dict] = None, at: Optional[datetime] = None,
) -> AuditLog:
    row = AuditLog(event=event, user_id=user_id, ip=ip, detail=detail or {}, at=at or utcnow())
    s.add(row)
    s.flush()
    return row


def list_audit(s: Session, limit: int = 100, before: Optional[int] = None) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
    if before is not None:
        q = q.where(AuditLog.id < before)
    return list(s.execute(q).scalars())


# ------------------------------------------------------------------ verdicts
def get_cached_verdict(s: Session, cache_key: str) -> Optional[AIVerdict]:
    return s.execute(
        select(AIVerdict).where(AIVerdict.cache_key == cache_key, AIVerdict.status == "ok")
    ).scalar_one_or_none()


def add_verdict(s: Session, **fields: Any) -> AIVerdict:
    row = AIVerdict(**fields)
    s.add(row)
    s.flush()
    return row


def latest_verdict_for_pair(s: Session, pair_key: str) -> Optional[AIVerdict]:
    return s.execute(
        select(AIVerdict).where(AIVerdict.pair_key == pair_key)
        .order_by(AIVerdict.id.desc()).limit(1)).scalar_one_or_none()


def recent_verdict_error(s: Session, pair_key: str, since: datetime) -> Optional[AIVerdict]:
    return s.execute(
        select(AIVerdict).where(
            AIVerdict.pair_key == pair_key, AIVerdict.status == "error",
            AIVerdict.created_at >= since)
        .order_by(AIVerdict.id.desc()).limit(1)).scalar_one_or_none()


# ------------------------------------------------------------------ analyses
def get_cached_analysis(s: Session, cache_key: str) -> Optional[AIAnalysis]:
    return s.execute(
        select(AIAnalysis).where(AIAnalysis.cache_key == cache_key)).scalar_one_or_none()


def latest_analysis_for_opportunity(s: Session, opportunity_key: str) -> Optional[AIAnalysis]:
    return s.execute(
        select(AIAnalysis).where(AIAnalysis.opportunity_key == opportunity_key)
        .order_by(AIAnalysis.id.desc()).limit(1)).scalar_one_or_none()


def add_analysis(s: Session, **fields: Any) -> AIAnalysis:
    row = AIAnalysis(**fields)
    s.add(row)
    s.flush()
    return row


# ------------------------------------------------------------- usage / budget
def get_usage_today(
    s: Session, now: Optional[datetime] = None
) -> dict[str, float]:
    """Aggregate usage across providers/models for the current UTC day."""
    rows = s.execute(select(AIUsageDaily).where(AIUsageDaily.day == utc_day(now))).scalars()
    total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for r in rows:
        total["calls"] += r.calls
        total["input_tokens"] += r.input_tokens
        total["output_tokens"] += r.output_tokens
        total["cost_usd"] += r.cost_usd
    return total


def record_usage(
    s: Session, provider: str, model: str, *, input_tokens: int = 0,
    output_tokens: int = 0, cost_usd: float = 0.0, now: Optional[datetime] = None,
) -> AIUsageDaily:
    day = utc_day(now)
    row = s.get(AIUsageDaily, (day, provider, model))
    if row is None:
        row = AIUsageDaily(day=day, provider=provider, model=model, calls=0,
                           input_tokens=0, output_tokens=0, cost_usd=0.0)
        s.add(row)
    row.calls += 1
    row.input_tokens += input_tokens
    row.output_tokens += output_tokens
    row.cost_usd += cost_usd
    s.flush()
    return row


# ------------------------------------------------------- opportunity history
def upsert_history(s: Session, opportunity_key: str, **fields: Any) -> OpportunityHistory:
    """Insert, or bump ``seen_count``/``last_seen_at``/``max_net_edge`` on the existing row."""
    now = utcnow()
    for attempt in (1, 2):
        row = s.execute(select(OpportunityHistory).where(
            OpportunityHistory.opportunity_key == opportunity_key)).scalar_one_or_none()
        if row is not None:
            for k, v in fields.items():
                setattr(row, k, v)
            row.last_seen_at = now
            row.seen_count += 1
            row.max_net_edge = max(row.max_net_edge, fields.get("net_edge", row.max_net_edge))
            s.flush()
            return row
        try:
            with s.begin_nested():
                row = OpportunityHistory(
                    opportunity_key=opportunity_key, first_seen_at=now, last_seen_at=now,
                    seen_count=1, max_net_edge=fields.get("net_edge", 0.0), **fields)
                s.add(row)
                s.flush()
            return row
        except IntegrityError:
            if attempt == 2:
                raise
    raise RuntimeError("unreachable")  # pragma: no cover


def list_history(s: Session, limit: int = 100, kind: Optional[str] = None) -> list[OpportunityHistory]:
    q = select(OpportunityHistory).order_by(OpportunityHistory.last_seen_at.desc()) \
        .limit(max(1, min(limit, 500)))
    if kind:
        q = q.where(OpportunityHistory.kind == kind)
    return list(s.execute(q).scalars())


# --------------------------------------------------------------- dismissals
def dismissed_pair_keys(s: Session) -> set[str]:
    return set(s.execute(select(PairDismissal.pair_key)).scalars())


def dismiss_pair(s: Session, pair_key: str, user_id: Optional[int], note: Optional[str] = None) -> None:
    row = s.get(PairDismissal, pair_key)
    if row is None:
        s.add(PairDismissal(pair_key=pair_key, user_id=user_id, note=note))
    else:
        row.user_id, row.note, row.dismissed_at = user_id, note, utcnow()
    s.flush()


def undismiss_pair(s: Session, pair_key: str) -> bool:
    res = s.execute(delete(PairDismissal).where(PairDismissal.pair_key == pair_key))
    return bool(res.rowcount)


# ----------------------------------------------------------------- settings
def get_overrides(s: Session) -> dict[str, Any]:
    return {r.key: r.value for r in s.execute(select(SettingOverride)).scalars()}


def set_override(s: Session, key: str, value: Any, updated_by: Optional[str]) -> None:
    row = s.get(SettingOverride, key)
    if row is None:
        s.add(SettingOverride(key=key, value=value, updated_by=updated_by))
    else:
        row.value, row.updated_by, row.updated_at = value, updated_by, utcnow()
    s.flush()
