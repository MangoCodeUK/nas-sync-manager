"""SQLAlchemy engine, session factory, and declarative base.

SQLite with a single connection-per-thread setup. The transfer engine runs in a
thread pool, so each worker opens its own Session.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings

settings = get_settings()

_url = make_url(settings.database_url)
_is_sqlite = _url.get_backend_name() == "sqlite"

# Ensure the SQLite parent directory exists (the file path may be relative to cwd
# or an absolute volume path like /data).
if _is_sqlite and _url.database:
    parent = os.path.dirname(os.path.abspath(_url.database))
    os.makedirs(parent, exist_ok=True)

# check_same_thread=False: sessions are used across the thread pool; SQLAlchemy's
# session-per-use pattern keeps this safe.
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
