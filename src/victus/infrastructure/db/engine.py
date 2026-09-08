"""Engine and session factory.

SQLite gets ``PRAGMA foreign_keys=ON`` on every connection (otherwise all
``REFERENCES`` are documentation only) and WAL journaling for concurrent
readers; an in-memory SQLite URL uses a ``StaticPool`` so every session sees
the same database.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def is_memory_sqlite(url: str) -> bool:
    return url in {"sqlite://", "sqlite:///:memory:"} or ":memory:" in url


def make_engine(url: str, *, echo: bool = False) -> Engine:
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if is_sqlite(url):
        kwargs["connect_args"] = {"check_same_thread": False}
        if is_memory_sqlite(url):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if is_sqlite(url):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if not is_memory_sqlite(url):
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=True)
