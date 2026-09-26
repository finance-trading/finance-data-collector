"""Shared offline fixtures for the filing parser test suite.

Every fixture uses SQLite so the suite never needs a live PostgreSQL server.
Settings are re-read per test because ``get_settings`` is cached per process.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from fdc.config import get_settings
from fdc.db import get_engine, get_session_factory
from fdc.models import create_all_for_tests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_FILINGS = PROJECT_ROOT / "tests" / "fixtures" / "filings"
TEST_USER_AGENT = "Collector test@example.com"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    """Keep environment-driven settings per test instead of per process."""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """Isolated SQLite database file for one test."""

    return f"sqlite:///{tmp_path / 'fdc-test.db'}"


@pytest.fixture
def engine(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Engine:
    """Engine with the full parser schema created."""

    monkeypatch.setenv("FDC_SEC_USER_AGENT", TEST_USER_AGENT)
    monkeypatch.setenv("FDC_DATABASE_URL", database_url)
    engine = get_engine(database_url)
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    create_all_for_tests(engine)
    return engine


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """ORM session for schema and persistence tests."""

    with Session(engine) as session:
        yield session


@pytest.fixture
def session_factory(database_url: str) -> sessionmaker[Session]:
    """Session factory used by the parse service and sync entry points."""

    return get_session_factory(database_url)
