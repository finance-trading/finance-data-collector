"""Fixtures for the browser-facing acceptance suite.

The acceptance tests run a real uvicorn server against a real (SQLite) seeded
database, so the browser exercises the same read API a local deployment uses.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from fdc.config import get_settings
from fdc.db import get_engine
from fdc.models import (
    Artifact,
    EvidenceLocator,
    ExtractedTable,
    Filing,
    FilingParse,
    FilingSection,
    Issuer,
    ParseRun,
    StatementLine,
    XbrlFact,
    create_all_for_tests,
)

PARSER_VERSION = "parser-v1"

#: 10-K with a successful current parse, 10-Q with a different successful parse.
ANNUAL_ACCESSION = "0000000000-24-000001"
QUARTER_ACCESSION = "0000000000-25-000002"
#: 10-Q whose only parse failed, used for the explicit "Parse failed" state.
FAILED_ACCESSION = "0000000000-24-000003"


def _seed_filing(
    session: Session,
    issuer: Issuer,
    *,
    accession: str,
    form: str,
    filing_date: date,
    report_date: date,
    revenue: float,
) -> None:
    """Seed one filing with a current successful parse and every output type."""

    filing = Filing(
        issuer_id=issuer.id,
        accession_number=accession,
        form=form,
        filing_date=filing_date,
        report_date=report_date,
        package_path=f"{form}/{accession}",
        primary_document=f"msft-{report_date:%Y%m%d}.htm",
        sec_url=f"https://www.sec.gov/Archives/edgar/data/789019/{accession.replace('-', '')}/",
    )
    session.add(filing)
    session.flush()
    run = ParseRun(
        scope_type="filing",
        scope_value=accession,
        parser_version=PARSER_VERSION,
        status="completed",
        started_at=datetime(2024, 8, 2, tzinfo=UTC),
        finished_at=datetime(2024, 8, 2, 0, 1, tzinfo=UTC),
        input_count=1,
        success_count=1,
    )
    session.add(run)
    session.flush()
    result = FilingParse(
        filing_id=filing.id,
        parse_run_id=run.id,
        artifact_set_hash=accession[:64].ljust(64, "0"),
        parser_version=PARSER_VERSION,
        parser_modules_hash="b" * 64,
        parser_modules={"statuses": {"edgartools_adapter": "success", "html_parser": "success"}},
        status="success",
        is_current=True,
        diagnostics={"counts": {"edgartools_adapter": {"facts": 1}}},
    )
    session.add(result)
    session.flush()
    artifact = Artifact(
        filing_id=filing.id,
        relative_path=f"{form}/{accession}/msft-{report_date:%Y%m%d}.htm",
        storage_uri=f"/fixture/msft-{report_date:%Y%m%d}.htm",
        content_type="text/html",
        byte_size=100,
        sha256="d" * 64,
        role="primary",
        classification_status="indexed",
    )
    session.add(artifact)
    session.flush()
    evidence = EvidenceLocator(
        filing_id=filing.id,
        artifact_id=artifact.id,
        relative_path=artifact.relative_path,
        accession_url=filing.sec_url,
        locator_type="xbrl_fact",
        locator_value="us-gaap:Revenue|context=FY2024",
        content_sha256=artifact.sha256,
        excerpt=f"Revenue {revenue:g}",
    )
    session.add(evidence)
    session.flush()
    context = {
        "source_filing_id": filing.id,
        "parse_run_id": run.id,
        "filing_parse_id": result.id,
        "evidence_locator_id": evidence.id,
        "parser_version": PARSER_VERSION,
    }
    session.add_all(
        [
            XbrlFact(
                **context,
                concept_namespace="us-gaap",
                concept="Revenue",
                label="Revenue",
                value_numeric=revenue,
                unit="USD",
                start_date=date(filing_date.year - 1, 10, 1),
                end_date=report_date,
                period_type="annual",
                accession=accession,
                form=form,
                extraction_method="xbrl",
            ),
            StatementLine(
                **context,
                statement_type="IncomeStatement",
                order_index=1,
                depth=0,
                label="Revenue",
                concept="us-gaap:Revenues",
                value_numeric=revenue,
                unit="USD",
                end_date=report_date,
                period_type="annual",
            ),
            StatementLine(
                **context,
                statement_type="IncomeStatement",
                order_index=2,
                depth=0,
                label="Net income",
                concept="us-gaap:NetIncomeLoss",
                value_numeric=revenue / 10,
                unit="USD",
                end_date=report_date,
                period_type="annual",
            ),
            StatementLine(
                **context,
                statement_type="BalanceSheet",
                order_index=1,
                depth=0,
                label="Total assets",
                concept="us-gaap:Assets",
                value_numeric=revenue * 4,
                unit="USD",
                end_date=report_date,
                period_type="instant",
            ),
            StatementLine(
                **context,
                statement_type="CashFlowStatement",
                order_index=1,
                depth=0,
                label="Operating cash flow",
                concept="us-gaap:NetCashProvidedByUsedInOperatingActivities",
                value_numeric=revenue / 5,
                unit="USD",
                end_date=report_date,
                period_type="annual",
            ),
            FilingSection(
                **context,
                section_type="md_and_a",
                heading="Item 7. Management's Discussion and Analysis",
                order_index=7,
                text="Liquidity remained strong through the period under review.",
                raw_fragment_hash="9" * 64,
                status="parsed",
            ),
            ExtractedTable(
                **context,
                table_type="debt_maturity",
                caption="Future maturities of debt",
                order_index=1,
                columns=["period", "amount"],
                rows=[["2027", "1200"], ["2028", "900"]],
                period_hints={"period": "2027"},
                extraction_method="html_table",
                confidence=0.9,
                status="parsed",
                raw_fragment_hash="8" * 64,
            ),
        ]
    )


def seed_fixture_database(database_url: str) -> None:
    """Create the schema and insert two parsed filings plus one explicit failure."""

    engine = get_engine(database_url)
    create_all_for_tests(engine)

    with Session(engine) as session:
        issuer = Issuer(
            cik="0000000000",
            name="Microsoft Fixture Corporation",
            ticker_hint="MSFT",
            sic="7372",
        )
        session.add(issuer)
        session.flush()
        _seed_filing(
            session,
            issuer,
            accession=ANNUAL_ACCESSION,
            form="10-K",
            filing_date=date(2024, 8, 1),
            report_date=date(2024, 6, 30),
            revenue=100,
        )
        _seed_filing(
            session,
            issuer,
            accession=QUARTER_ACCESSION,
            form="10-Q",
            filing_date=date(2025, 1, 25),
            report_date=date(2024, 12, 31),
            revenue=120,
        )
        failed_filing = Filing(
            issuer_id=issuer.id,
            accession_number=FAILED_ACCESSION,
            form="10-Q",
            filing_date=date(2024, 5, 1),
            report_date=date(2024, 3, 31),
            package_path=f"10-Q/{FAILED_ACCESSION}",
        )
        session.add(failed_filing)
        session.flush()
        failed_run = ParseRun(
            scope_type="filing",
            scope_value=FAILED_ACCESSION,
            parser_version=PARSER_VERSION,
            status="failed",
            input_count=1,
            failure_count=1,
            error_summary={"errors": [{"detail": "XBRL parse failed"}]},
        )
        session.add(failed_run)
        session.flush()
        session.add(
            FilingParse(
                filing_id=failed_filing.id,
                parse_run_id=failed_run.id,
                artifact_set_hash="c" * 64,
                parser_version=PARSER_VERSION,
                parser_modules_hash="b" * 64,
                status="failed",
                is_current=False,
                diagnostics={"detail": "XBRL parse failed"},
            )
        )
        session.commit()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Run uvicorn over a seeded SQLite database and yield its base URL."""

    database_url = f"sqlite:///{tmp_path_factory.mktemp('acceptance') / 'acceptance.db'}"
    names = ("FDC_DATABASE_URL", "FDC_PARSER_VERSION", "FDC_SEC_USER_AGENT")
    saved = {name: os.environ.get(name) for name in names}
    os.environ["FDC_DATABASE_URL"] = database_url
    os.environ["FDC_PARSER_VERSION"] = PARSER_VERSION
    os.environ.setdefault("FDC_SEC_USER_AGENT", "Collector test@example.com")
    get_settings.cache_clear()
    seed_fixture_database(database_url)

    import uvicorn

    from fdc.api import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start within 20s")
        if not thread.is_alive():
            raise RuntimeError("uvicorn exited during startup")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=15)
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def browser():
    """A headless Chromium; skipped when Playwright browsers are not installed."""

    from playwright.sync_api import sync_playwright

    manager = sync_playwright().start()
    try:
        instance = manager.chromium.launch()
    except Exception as error:  # pragma: no cover - environment dependent
        manager.stop()
        pytest.skip(f"chromium unavailable, run `uv run playwright install chromium` ({error})")
    yield instance
    instance.close()
    manager.stop()
