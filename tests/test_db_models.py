import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
import pytest

from app import repo
from app.clock import utcnow
from app.db import init_database
from app.models import Base


def test_migration_matches_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    init_database(url, auto_migrate=True).dispose()
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    tables = set(inspect(engine).get_table_names())
    assert {"users", "sessions", "ai_verdicts", "ai_analyses", "opportunity_history",
            "audit_log", "ai_usage_daily", "pair_dismissals", "settings_overrides"} <= tables


def test_sqlite_pragmas(db):
    with db.engine.connect() as c:
        assert c.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert c.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"


def test_username_unique(db):
    with db.session() as s:
        repo.create_user(s, "a", "h")
    with pytest.raises(IntegrityError):
        with db.session() as s:
            repo.create_user(s, "A", "h")  # usernames are case-insensitive


def test_session_fk_enforced(db):
    with pytest.raises(IntegrityError):
        with db.session() as s:
            repo.create_session_row(s, id="x", user_id=999, csrf_token="c",
                                    expires_at=utcnow(), created_at=utcnow(), last_seen_at=utcnow())


def test_verdict_cache_key_unique_and_errors_not_cached(db):
    base = dict(pair_key="p", platform_a="polymarket", market_a_id="1", platform_b="kalshi",
                market_b_id="K", provider="mock", model="m", prompt_version="v1")
    with db.session() as s:
        repo.add_verdict(s, cache_key="k1", status="ok", verdict="identical",
                         confidence=0.9, **base)
        repo.add_verdict(s, cache_key="err:1", status="error", error="boom", **base)
    with pytest.raises(IntegrityError):
        with db.session() as s:
            repo.add_verdict(s, cache_key="k1", status="ok", **base)
    with db.session() as s:
        assert repo.get_cached_verdict(s, "k1").verdict == "identical"
        assert repo.get_cached_verdict(s, "err:1") is None


def test_history_upsert(db):
    kw = dict(kind="cross_platform", pair_key="p", platforms="polymarket|kalshi",
              gross_edge=0.1, actionable=True, verification_status="verified")
    with db.session() as s:
        repo.upsert_history(s, "opp1", net_edge=0.05, **kw)
    with db.session() as s:
        repo.upsert_history(s, "opp1", net_edge=0.09, **kw)
    with db.session() as s:
        row = repo.upsert_history(s, "opp1", net_edge=0.02, **kw)
        assert row.seen_count == 3
        assert row.max_net_edge == 0.09
        assert row.net_edge == 0.02
        assert len(repo.list_history(s)) == 1


def test_budget_day_rollover(db):
    from datetime import datetime
    d1, d2 = datetime(2026, 3, 1, 23, 59), datetime(2026, 3, 2, 0, 1)
    with db.session() as s:
        repo.record_usage(s, "gemini", "m", input_tokens=10, output_tokens=5, cost_usd=0.01, now=d1)
        repo.record_usage(s, "gemini", "m", input_tokens=10, output_tokens=5, cost_usd=0.01, now=d1)
        repo.record_usage(s, "mock", "m", now=d1)
        assert repo.get_usage_today(s, d1)["calls"] == 3
        assert repo.get_usage_today(s, d2)["calls"] == 0
        repo.record_usage(s, "gemini", "m", now=d2)
        assert repo.get_usage_today(s, d2)["calls"] == 1
        assert repo.get_usage_today(s, d1)["calls"] == 3


def test_dismissals_and_overrides(db):
    with db.session() as s:
        repo.dismiss_pair(s, "pair", None, "note")
        assert repo.dismissed_pair_keys(s) == {"pair"}
        assert repo.undismiss_pair(s, "pair") is True
        assert repo.undismiss_pair(s, "pair") is False
        repo.set_override(s, "ai.enabled", False, "owner")
        repo.set_override(s, "ai.enabled", True, "owner")
        assert repo.get_overrides(s) == {"ai.enabled": True}
