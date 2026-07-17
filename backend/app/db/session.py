"""Engine / session helpers with SQLite or Postgres support."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine() -> Engine:
    """Return (and lazily create) the process-wide SQLAlchemy engine."""
    global _engine, SessionLocal
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.database_url
    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args=_sqlite_connect_args(url),
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engine = engine
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine


def dispose_engine() -> None:
    """Dispose the engine (tests)."""
    global _engine, SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    SessionLocal = None


def init_db() -> None:
    """Create tables and ensure media directories exist."""
    from app.services.media import ensure_media_dirs

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ensure_media_dirs()
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _seed_if_empty()


def _seed_if_empty() -> None:
    """Seed demo records / planogram / admin user when the DB is empty."""
    from app.services.auth import ensure_default_admin
    from app.services.planogram_store import get_planogram_store
    from app.services.store import get_store

    # Touch stores so they run their own empty-DB seed paths.
    get_store()
    get_planogram_store()
    ensure_default_admin()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a transactional session; commits on success, rolls back on error."""
    get_engine()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def session_scalar_exists(session: Session, model, **filters) -> bool:
    """Return True when at least one row matches the filters."""
    stmt = select(model).filter_by(**filters).limit(1)
    return session.scalars(stmt).first() is not None
