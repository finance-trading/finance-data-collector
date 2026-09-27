"""Read-only API coverage against the real parser persistence schema."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from fdc import catalog
from fdc.api import app
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
)

ACCESSION = "0000000000-24-000001"
FAILED_ACCESSION = "0000000000-24-000002"
UNPARSED_ACCESSION = "0000000000-24-000003"


@pytest.fixture
def seeded_database(session, database_url, monkeypatch):
    monkeypatch.setenv("FDC_DATABASE_URL", database_url)
    monkeypatch.setenv("FDC_PARSER_VERSION", "parser-v1")
    issuer = Issuer(
        cik="0000000000",
        name="Microsoft Fixture Corporation",
        ticker_hint="MSFT",
        sic="7372",
    )
    session.add(issuer)
    session.flush()
    filing = Filing(
        issuer_id=issuer.id,
        accession_number=ACCESSION,
        form="10-K",
        filing_date=date(2024, 8, 1),
        report_date=date(2024, 6, 30),
        package_path="MSFT/10-K/0000000000-24-000001",
        primary_document="msft.htm",
        sec_url="https://www.sec.gov/Archives/fixture",
    )
    failed_filing = Filing(
        issuer_id=issuer.id,
        accession_number=FAILED_ACCESSION,
        form="10-Q",
        filing_date=date(2024, 5, 1),
        report_date=date(2024, 3, 31),
        package_path="MSFT/10-Q/0000000000-24-000002",
    )
    unparsed_filing = Filing(
        issuer_id=issuer.id,
        accession_number=UNPARSED_ACCESSION,
        form="10-Q",
        filing_date=date(2024, 2, 1),
        report_date=date(2023, 12, 31),
        package_path="MSFT/10-Q/0000000000-24-000003",
    )
    session.add_all([filing, failed_filing, unparsed_filing])
    session.flush()
    run = ParseRun(
        scope_type="ticker",
        scope_value="MSFT",
        parser_version="parser-v1",
        status="completed",
        started_at=datetime(2024, 8, 2, tzinfo=UTC),
        finished_at=datetime(2024, 8, 2, 0, 1, tzinfo=UTC),
        input_count=1,
        success_count=1,
        failure_count=0,
        checkpoint_accession=ACCESSION,
        error_summary={"errors": []},
    )
    failed_run = ParseRun(
        scope_type="filing",
        scope_value=FAILED_ACCESSION,
        parser_version="parser-v1",
        status="failed",
        input_count=1,
        failure_count=1,
        error_summary={"errors": [{"detail": "XBRL parse failed"}]},
    )
    historical_run = ParseRun(
        scope_type="filing",
        scope_value=ACCESSION,
        parser_version="parser-old",
        status="completed",
        input_count=1,
        success_count=1,
    )
    session.add_all([run, failed_run, historical_run])
    session.flush()
    current = FilingParse(
        filing_id=filing.id,
        parse_run_id=run.id,
        artifact_set_hash="a" * 64,
        parser_version="parser-v1",
        parser_modules_hash="b" * 64,
        parser_modules={"statuses": {"edgartools_adapter": "success", "html_parser": "success"}},
        status="success",
        is_current=True,
        diagnostics={"counts": {"edgartools_adapter": {"facts": 1}}},
    )
    failed = FilingParse(
        filing_id=failed_filing.id,
        parse_run_id=failed_run.id,
        artifact_set_hash="c" * 64,
        parser_version="parser-v1",
        parser_modules_hash="b" * 64,
        status="failed",
        is_current=False,
        diagnostics={"detail": "XBRL parse failed"},
    )
    other_version_current = FilingParse(
        filing_id=filing.id,
        parse_run_id=historical_run.id,
        artifact_set_hash="e" * 64,
        parser_version="parser-old",
        parser_modules_hash="f" * 64,
        status="success",
        is_current=True,
        diagnostics={"detail": "must not be served"},
    )
    session.add_all([other_version_current, current, failed])
    session.flush()
    artifact = Artifact(
        filing_id=filing.id,
        relative_path="10-K/0000000000-24-000001/msft.htm",
        storage_uri="/fixture/msft.htm",
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
        accession_url="https://www.sec.gov/Archives/fixture#revenue",
        locator_type="xbrl_fact",
        locator_value="us-gaap:Revenue|context=FY2024",
        content_sha256=artifact.sha256,
        excerpt="Revenue 100",
    )
    session.add(evidence)
    session.flush()
    common = {
        "source_filing_id": filing.id,
        "parse_run_id": run.id,
        "filing_parse_id": current.id,
        "evidence_locator_id": evidence.id,
        "parser_version": "parser-v1",
    }
    session.add_all(
        [
            XbrlFact(
                **common,
                concept_namespace="us-gaap",
                concept="Revenue",
                label="Revenue",
                value_numeric=100,
                unit="USD",
                start_date=date(2023, 7, 1),
                end_date=date(2024, 6, 30),
                period_type="annual",
                accession=ACCESSION,
                form="10-K",
                extraction_method="xbrl",
            ),
            StatementLine(
                **common,
                statement_type="income",
                order_index=1,
                depth=0,
                label="Revenue",
                concept="Revenue",
                value_numeric=100,
                unit="USD",
                end_date=date(2024, 6, 30),
                period_type="annual",
            ),
            FilingSection(
                **common,
                section_type="md_and_a",
                heading="Item 7",
                order_index=1,
                text="Liquidity remained strong.",
                status="parsed",
                diagnostics=[],
            ),
            ExtractedTable(
                **common,
                table_type="debt_maturity",
                caption="Debt maturities",
                order_index=1,
                columns=["Year", "Amount"],
                rows=[["2025", "10"]],
                extraction_method="html_table",
                confidence=0.9,
                status="parsed",
                diagnostics=[],
            ),
        ]
    )
    session.commit()
    return {"run_id": str(run.id), "evidence_id": str(evidence.id)}


@pytest.fixture
def client(seeded_database):
    class ApiClient:
        def get(self, path: str) -> httpx.Response:
            async def request() -> httpx.Response:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                ) as async_client:
                    return await async_client.get(path)

            return asyncio.run(request())

    return ApiClient()


def test_api_registers_only_get_read_routes():
    """Regression: adding a write verb would violate the HTTP boundary."""

    methods = {
        method
        for route in app.routes
        if route.path.startswith("/api/v1")
        for method in route.methods
    }
    assert methods == {"GET"}


def test_company_and_filtered_filing_list_expose_parse_state(client):
    company = client.get("/api/v1/companies/msft")
    filings = client.get("/api/v1/companies/MSFT/filings?form=10-K&limit=1&offset=0")

    assert company.status_code == 200
    assert company.json()["ticker"] == "MSFT"
    assert company.json()["latest_filing_status"] == "success"
    assert filings.status_code == 200
    assert filings.json()["total"] == 1
    assert filings.json()["filings"][0] == {
        "accession": ACCESSION,
        "form": "10-K",
        "filing_date": "2024-08-01",
        "report_date": "2024-06-30",
        "status": "success",
        "parser_version": "parser-v1",
        "diagnostics": {"counts": {"edgartools_adapter": {"facts": 1}}},
    }


def test_company_directory_supports_name_search(client):
    response = client.get("/api/v1/companies?query=microsoft&limit=10&offset=0")

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "microsoft"
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert payload["total"] == 1
    assert payload["companies"][0]["ticker"] == "MSFT"
    assert payload["companies"][0]["cik"] == "0000000000"
    assert payload["companies"][0]["latest_filing_date"] == "2024-08-01"
    assert payload["companies"][0]["latest_filing_status"] == "success"
    assert payload["companies"][0]["ingestion_status"] == "parsed"
    assert payload["companies"][0]["research_available"] is True
    assert payload["companies"][0]["filing_count"] == 3


def test_company_directory_paginates_the_complete_catalog(client):
    first = client.get("/api/v1/companies?limit=25&offset=0")
    last = client.get("/api/v1/companies?limit=25&offset=200")

    assert first.status_code == 200
    assert first.json()["total"] == 211
    assert len(first.json()["companies"]) == 25
    assert len(last.json()["companies"]) == 11


def test_company_directory_combines_layer_and_status_filters(client):
    response = client.get(
        "/api/v1/companies?layer=silicon&ingestion_status=not_ingested&limit=100"
    )

    assert response.status_code == 200
    assert response.json()["companies"]
    assert all(item["layer"] == "silicon" for item in response.json()["companies"])
    assert all(
        item["ingestion_status"] == "not_ingested"
        for item in response.json()["companies"]
    )


def test_catalog_layers_expose_the_complete_ai_universe(client):
    response = client.get("/api/v1/catalog/layers")

    assert response.status_code == 200
    assert response.json()["total_companies"] == 211
    assert response.json()["layers"][0]["id"] == "power"
    assert response.json()["layers"][0]["count"] == 16


def test_graph_visualization_is_served_by_the_read_api(client):
    response = client.get("/api/v1/visualizations/graph")

    assert response.status_code == 200
    assert len(response.json()["nodes"]) == 211


def test_missing_visualization_has_an_explicit_unavailable_state(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(catalog, "GRAPH_PATH", tmp_path / "missing.json")

    response = client.get("/api/v1/visualizations/graph")

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "unavailable"


def test_company_prefers_same_ticker_issuer_with_the_latest_filing(
    client, session, seeded_database
):
    latest_accession = "0000000001-25-000001"
    issuer = Issuer(
        cik="0000000001",
        name="Microsoft Current Corporation",
        ticker_hint="MSFT",
    )
    session.add(issuer)
    session.flush()
    filing = Filing(
        issuer_id=issuer.id,
        accession_number=latest_accession,
        form="10-Q",
        filing_date=date(2025, 5, 1),
        report_date=date(2025, 3, 31),
        package_path=f"MSFT/10-Q/{latest_accession}",
    )
    run = ParseRun(
        scope_type="filing",
        scope_value=latest_accession,
        parser_version="parser-v1",
        status="completed",
        started_at=datetime(2025, 5, 2, tzinfo=UTC),
    )
    session.add_all([filing, run])
    session.flush()
    session.add(
        FilingParse(
            filing_id=filing.id,
            parse_run_id=run.id,
            artifact_set_hash="f" * 64,
            parser_version="parser-v1",
            parser_modules_hash="1" * 64,
            status="success",
            is_current=True,
        )
    )
    session.commit()

    company = client.get("/api/v1/companies/MSFT")
    filings = client.get("/api/v1/companies/MSFT/filings")

    assert company.status_code == 200
    assert company.json()["cik"] == "0000000001"
    assert company.json()["latest_filing_date"] == "2025-05-01"
    assert filings.status_code == 200
    assert filings.json()["filings"][0]["accession"] == latest_accession


def test_filing_api_exposes_current_parser_identity(client):
    response = client.get(f"/api/v1/filings/{ACCESSION}")

    assert response.status_code == 200
    assert response.json()["parse"]["status"] == "success"
    assert response.json()["parse"]["parser_version"] == "parser-v1"
    assert response.json()["filing_date"] == "2024-08-01"
    assert response.json()["report_date"] == "2024-06-30"


@pytest.mark.parametrize(
    ("accession", "expected_code", "expected_state"),
    [
        (UNPARSED_ACCESSION, 409, "unavailable"),
        (FAILED_ACCESSION, 422, "failed"),
    ],
)
def test_filing_detail_requires_current_success(
    client, accession, expected_code, expected_state
):
    """Regression: filing detail must not serve failed or unparsed output as 200."""

    response = client.get(f"/api/v1/filings/{accession}")

    assert response.status_code == expected_code
    assert response.json()["detail"]["status"] == expected_state
    assert "diagnostics" in response.json()["detail"]


def test_filing_api_exposes_fact_and_statement_evidence(client):
    facts = client.get(f"/api/v1/filings/{ACCESSION}/facts?concept=Revenue")
    statements = client.get(
        f"/api/v1/filings/{ACCESSION}/statements?statement_type=income"
    )

    assert facts.status_code == 200
    assert facts.json()["facts"][0]["evidence"]["accession"] == ACCESSION
    assert facts.json()["facts"][0]["concept"] == "Revenue"
    assert statements.status_code == 200
    assert statements.json()["lines"][0]["evidence"]["evidence_id"]


def test_fact_api_serializes_large_decimal_without_binary_float_loss(
    client, session, seeded_database
):
    fact = session.scalar(select(XbrlFact).where(XbrlFact.concept == "Revenue"))
    assert fact is not None
    fact.value_numeric = Decimal("9007199254740993.125")
    session.commit()

    response = client.get(f"/api/v1/filings/{ACCESSION}/facts?concept=Revenue")

    assert response.status_code == 200
    assert response.json()["facts"][0]["value_numeric"] == "9007199254740993.125"


def test_filing_api_exposes_sections_tables_and_evidence(client, seeded_database):
    section = client.get(f"/api/v1/filings/{ACCESSION}/sections/md_and_a")
    tables = client.get(
        f"/api/v1/filings/{ACCESSION}/tables?table_type=debt_maturity"
    )
    evidence = client.get(
        f"/api/v1/filings/{ACCESSION}/evidence/{seeded_database['evidence_id']}"
    )

    assert section.status_code == 200
    assert section.json()["status"] == "parsed"
    assert section.json()["evidence"]["accession"] == ACCESSION
    assert tables.status_code == 200
    assert tables.json()["tables"][0]["rows"] == [["2025", "10"]]
    assert evidence.status_code == 200
    assert evidence.json()["content_sha256"] == "d" * 64


def _add_mixed_tables(session, *, table_type, non_success_status):
    current = session.scalar(
        select(FilingParse).where(
            FilingParse.parser_version == "parser-v1",
            FilingParse.is_current.is_(True),
        )
    )
    evidence = session.scalar(select(EvidenceLocator))
    assert current is not None and evidence is not None
    common = {
        "source_filing_id": current.filing_id,
        "parse_run_id": current.parse_run_id,
        "filing_parse_id": current.id,
        "evidence_locator_id": evidence.id,
        "parser_version": current.parser_version,
        "table_type": table_type,
    }
    session.add_all(
        [
            ExtractedTable(
                **common,
                order_index=10,
                rows=[["parsed"]],
                status="parsed",
                diagnostics=[],
            ),
            ExtractedTable(
                **common,
                order_index=11,
                rows=[],
                status=non_success_status,
                diagnostics=[{"code": "TABLE_GAP", "detail": "fixture gap"}],
            ),
        ]
    )
    session.commit()


@pytest.mark.parametrize(
    ("table_type", "row_status"),
    [
        ("mixed_failed", "failed"),
        ("mixed_unavailable", "unavailable"),
    ],
)
def test_mixed_table_results_return_usable_rows_with_partial_diagnostics(
    client,
    session,
    table_type,
    row_status,
):
    """A scoped table failure must not hide a usable peer."""

    _add_mixed_tables(session, table_type=table_type, non_success_status=row_status)

    response = client.get(
        f"/api/v1/filings/{ACCESSION}/tables?table_type={table_type}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert [table["rows"] for table in payload["tables"]] == [[["parsed"]]]
    assert len(payload["diagnostics"]["tables"]) == 1
    diagnostic = payload["diagnostics"]["tables"][0]
    assert diagnostic["table_id"]
    assert diagnostic["status"] == row_status
    assert diagnostic["diagnostics"] == [{"code": "TABLE_GAP", "detail": "fixture gap"}]


@pytest.mark.parametrize(
    ("table_type", "row_status", "expected_code", "expected_state"),
    [
        ("only_failed", "failed", 422, "failed"),
        ("only_unavailable", "unavailable", 409, "unavailable"),
    ],
)
def test_table_api_errors_only_when_no_requested_table_is_usable(
    client, session, table_type, row_status, expected_code, expected_state
):
    _add_mixed_tables(session, table_type=table_type, non_success_status=row_status)
    parsed = session.scalar(
        select(ExtractedTable).where(
            ExtractedTable.table_type == table_type,
            ExtractedTable.status == "parsed",
        )
    )
    assert parsed is not None
    session.delete(parsed)
    session.commit()

    response = client.get(f"/api/v1/filings/{ACCESSION}/tables?table_type={table_type}")

    assert response.status_code == expected_code
    assert response.json()["detail"]["status"] == expected_state


def test_parse_run_api_exposes_counts_and_accession_diagnostics(client, seeded_database):
    response = client.get(f"/api/v1/parse-runs/{seeded_database['run_id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["checkpoint_accession"] == ACCESSION
    assert response.json()["errors"] == []


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_state"),
    [
        ("/api/v1/companies/UNKNOWN", 404, "not_found"),
        (f"/api/v1/filings/{UNPARSED_ACCESSION}/facts", 409, "unavailable"),
        (f"/api/v1/filings/{FAILED_ACCESSION}/facts", 422, "failed"),
        (f"/api/v1/filings/{ACCESSION}/facts?concept=MissingConcept", 409, "unavailable"),
    ],
)
def test_api_preserves_not_found_unavailable_and_failed_states(
    client, path, expected_status, expected_state
):
    response = client.get(path)

    assert response.status_code == expected_status
    assert response.json()["detail"]["status"] == expected_state
    assert "diagnostics" in response.json()["detail"]
