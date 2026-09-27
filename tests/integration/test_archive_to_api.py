"""Unmocked local archive -> parser -> current result -> read API round trip."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import select

from alembic import command
from fdc.api import app
from fdc.config import get_settings
from fdc.db import get_session_factory
from fdc.models import FilingParse
from fdc.sync import parse_ticker

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "filings"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_local_archive_parses_to_current_and_is_served_by_api(
    engine, session_factory, database_url, monkeypatch
):
    monkeypatch.delenv("FDC_SEC_USER_AGENT", raising=False)
    monkeypatch.setenv("FDC_DATABASE_URL", database_url)

    run = parse_ticker(session_factory, "MSFT", FIXTURE_ROOT)

    assert run.status == "completed"
    assert run.success_count == 2
    with session_factory() as session:
        current = session.scalars(
            select(FilingParse).where(FilingParse.is_current.is_(True))
        ).all()
        assert len(current) == 2

    async def request(path: str) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    filing = asyncio.run(request("/api/v1/filings/0000000000-24-000001"))
    facts = asyncio.run(request("/api/v1/filings/0000000000-24-000001/facts"))

    assert filing.status_code == 200
    assert filing.json()["parse"]["status"] == "success"
    assert filing.json()["sec_url"].startswith("https://www.sec.gov/Archives/edgar/data/")
    assert facts.status_code == 200
    assert facts.json()["facts"]
    assert facts.json()["facts"][0]["evidence"]["accession_url"].startswith(
        "https://www.sec.gov/Archives/edgar/data/"
    )


@pytest.mark.skipif(
    not os.environ.get("FDC_TEST_POSTGRES_URL"),
    reason="FDC_TEST_POSTGRES_URL is not configured",
)
def test_postgres_migration_parse_and_read_api_round_trip(monkeypatch):
    database_url = os.environ["FDC_TEST_POSTGRES_URL"]
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    monkeypatch.setenv("FDC_DATABASE_URL", database_url)
    monkeypatch.setenv("FDC_PARSER_VERSION", "postgres-roundtrip-v1")
    monkeypatch.delenv("FDC_SEC_USER_AGENT", raising=False)
    get_settings.cache_clear()
    session_factory = get_session_factory(database_url)

    run = parse_ticker(
        session_factory,
        "MSFT",
        FIXTURE_ROOT,
        force=True,
        parser_version="postgres-roundtrip-v1",
    )

    assert run.status == "completed"
    response = asyncio.run(_api_get("/api/v1/filings/0000000000-24-000001/facts"))
    assert response.status_code == 200
    assert response.json()["facts"]


async def _api_get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)
