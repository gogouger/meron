"""SQLite database layer for MERON.

Provides SQLAlchemy engine, session factory, and a helper to get the
canonical DB path (`$MERON_DB_PATH` env var, default `~/.meron/meron.db`).
"""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_SessionFactory: sessionmaker | None = None


def default_db_path() -> Path:
    override = os.environ.get("MERON_DB_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".meron" / "meron.db"


def meron_dir() -> Path:
    """Root directory for MERON data (db, fit files, uploads, sidecar json)."""
    return default_db_path().parent


def init_engine(db_path: Path | str | None = None):
    """Create the SQLAlchemy engine + session factory. Idempotent."""
    global _engine, _SessionFactory
    if _engine is not None:
        return _engine
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{path}", future=True)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    if _SessionFactory is None:
        init_engine()
    return _SessionFactory  # type: ignore[return-value]


@contextmanager
def session_scope() -> Session:
    """Provide a transactional scope around a series of operations."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
