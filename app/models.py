"""SQLAlchemy ORM models. Timestamps are naive UTC."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.clock import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="owner", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SessionRow(Base):
    """A login session. ``id`` is the hash of the cookie token, never the token."""
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class AIVerdict(Base):
    __tablename__ = "ai_verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Successful verdicts are keyed by the content hash; error rows get a
    # synthetic unique key so they are recorded but never served from cache.
    cache_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    pair_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform_a: Mapped[str] = mapped_column(String(32), nullable=False)
    market_a_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform_b: Mapped[str] = mapped_column(String(32), nullable=False)
    market_b_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)  # ok | error
    verdict: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    differences: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    short_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AIAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    opportunity_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    verdict_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ai_verdicts.id", ondelete="SET NULL"), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[Any] = mapped_column(JSON, nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class OpportunityHistory(Base):
    __tablename__ = "opportunity_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # bundle | cross_platform
    pair_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    platforms: Mapped[str] = mapped_column(String(64), nullable=False)
    market_a_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    market_b_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    net_edge: Mapped[float] = mapped_column(Float, nullable=False)
    gross_edge: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fees: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verification_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    actionable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    seen_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_net_edge: Mapped[float] = mapped_column(Float, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_at", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # login_success | login_failure | lockout | logout | session_expired |
    # config_change | user_created
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)


class AIUsageDaily(Base):
    """Per-day AI usage; persisted so the budget survives restarts."""
    __tablename__ = "ai_usage_daily"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class PairDismissal(Base):
    """Dismissal is per pair, not per content hash."""
    __tablename__ = "pair_dismissals"

    pair_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class SettingOverride(Base):
    """Runtime settings changed from the UI. Whitelisted keys only."""
    __tablename__ = "settings_overrides"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
