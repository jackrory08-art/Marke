"""Database engine, session factory and migrations (sync SQLAlchemy 2.0).

Async code calls into this through ``asyncio.to_thread``; FastAPI sync
dependencies already run in the threadpool. Moving to Postgres only means
changing ``DATABASE_URL``.
"""

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Database:
    """Owns the engine and hands out sessions."""

    def __init__(self, url: str):
        self.url = url
        self.engine = make_engine(url)
        self._sessionmaker = sessionmaker(
            self.engine, expire_on_commit=False, class_=Session)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commit on success, roll back on error."""
        session = self._sessionmaker()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    is_sqlite = parsed.get_backend_name() == "sqlite"
    kwargs: dict = {"future": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        db_path = parsed.database
        if db_path and db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    return engine


def alembic_config(url: str):
    from alembic.config import Config
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def run_migrations(url: str) -> None:
    """Run ``alembic upgrade head`` against ``url``."""
    from alembic import command
    logger.info("Running database migrations")
    command.upgrade(alembic_config(url), "head")


def init_database(url: str, auto_migrate: bool = True) -> Database:
    """Create a Database, migrating it to head first when asked."""
    if auto_migrate:
        run_migrations(url)
    return Database(url)
