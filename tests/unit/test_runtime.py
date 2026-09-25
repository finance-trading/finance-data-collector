"""Unit tests for the parser runtime settings and database helpers.

Everything here runs offline on SQLite: importing ``fdc.db`` and creating a
session must never require a live PostgreSQL server.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from fdc.config import get_settings
from fdc.db import get_engine, get_session_factory, session_scope


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _use_sqlite(monkeypatch, tmp_path, name="collector.db"):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setenv("FDC_DATABASE_URL", f"sqlite:///{tmp_path / name}")


def test_parser_settings_are_explicit(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setenv("FDC_PARSER_VERSION", "filing-parser-v1")
    settings = get_settings()
    assert settings.parser_version == "filing-parser-v1"
    assert settings.sec_root == "./sec"


def test_parser_settings_use_documented_defaults(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    for key in (
        "FDC_PARSER_VERSION",
        "FDC_SEC_ROOT",
        "FDC_DATABASE_URL",
        "FDC_EDGARTOOLS_VERSION",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.parser_version == "filing-parser-v1"
    assert settings.sec_root == "./sec"
    assert settings.edgartools_version is None


def test_session_scope_commits_on_success(tmp_path, monkeypatch):
    _use_sqlite(monkeypatch, tmp_path)
    with session_scope() as session:
        session.execute(text("CREATE TABLE probe (value INTEGER)"))
        session.execute(text("INSERT INTO probe (value) VALUES (1)"))

    with session_scope() as session:
        assert session.execute(text("SELECT value FROM probe")).scalar_one() == 1


def test_session_scope_rolls_back_on_error(tmp_path, monkeypatch):
    _use_sqlite(monkeypatch, tmp_path)
    with session_scope() as session:
        session.execute(text("CREATE TABLE probe (value INTEGER)"))

    with pytest.raises(RuntimeError):
        with session_scope() as session:
            session.execute(text("INSERT INTO probe (value) VALUES (2)"))
            raise RuntimeError("rollback")

    with session_scope() as session:
        assert session.execute(text("SELECT count(*) FROM probe")).scalar_one() == 0


def test_engine_and_session_factory_are_reused_per_url(tmp_path, monkeypatch):
    _use_sqlite(monkeypatch, tmp_path, name="reuse.db")

    assert get_engine() is get_engine()
    assert get_session_factory() is get_session_factory()


def test_session_scope_without_tables_still_connects(tmp_path, monkeypatch):
    _use_sqlite(monkeypatch, tmp_path, name="ping.db")

    with session_scope() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
