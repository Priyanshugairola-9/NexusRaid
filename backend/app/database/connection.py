"""Database engine and session handling.

SQLAlchemy hides the differences between SQLite and PostgreSQL, so the rest of
the app never talks to a specific database directly. All times are stored as
UTC without a time-zone marker (the same way in SQLite and PostgreSQL).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Parent class for all database tables."""


def _build_engine() -> Engine:
    settings = get_settings()
    connect_args = {}
    if settings.is_sqlite:
        # FastAPI may serve requests on several threads. Each request still gets
        # its own session, so allowing cross-thread use is safe here.
        connect_args["check_same_thread"] = False
    engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
    if settings.is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked
            cursor.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer
            cursor.close()
    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: open one session per request and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create missing tables.

    Limitation: this creates new tables but never alters existing ones. Before a
    long-lived PostgreSQL deployment, introduce Alembic migrations.
    """
    from app.database import models  # noqa: F401  (importing registers the tables)

    Base.metadata.create_all(bind=engine)
