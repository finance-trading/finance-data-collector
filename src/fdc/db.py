"""Database engine and session helpers for the filing parser platform.

The module is import-safe: engines are created lazily per database URL, so
importing :mod:`fdc.db` never requires a reachable PostgreSQL server.  Tests
run on SQLite (file or in-memory) through the same helpers as production.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fdc.config import get_settings

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}
_lock = Lock()


def _engine_options(url: str) -> dict[str, object]:
    """Return engine options that keep SQLite test backends usable."""

    if url.startswith("sqlite"):
        options: dict[str, object] = {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        return options
    return {"pool_pre_ping": True}


def get_engine(database_url: str | None = None) -> Engine:
    """Return the pooled engine for ``database_url`` (default: settings)."""

    url = database_url or get_settings().database_url
    engine = _engines.get(url)
    if engine is None:
        with _lock:
            engine = _engines.get(url)
            if engine is None:
                engine = create_engine(url, **_engine_options(url))
                _engines[url] = engine
    return engine


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Return the cached session factory bound to ``database_url``."""

    url = database_url or get_settings().database_url
    factory = _session_factories.get(url)
    if factory is None:
        # Resolve the engine before locking: get_engine takes the same lock.
        engine = get_engine(url)
        with _lock:
            factory = _session_factories.get(url)
            if factory is None:
                factory = sessionmaker(bind=engine, expire_on_commit=False)
                _session_factories[url] = factory
    return factory


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """Yield a session, commit on success, roll back and close on error."""

    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class _LazySessionFactory:
    """Session factory resolved against the current settings on every call."""

    def __call__(self, **kwargs: object) -> Session:
        return get_session_factory()(**kwargs)


SessionLocal = _LazySessionFactory()
