"""Read-only FastAPI application for current filing parse results."""

from __future__ import annotations

from typing import Annotated, Callable, TypeVar

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from fdc import read_service
from fdc.read_service import (
    CompanyView,
    EvidenceView,
    FactView,
    FilingListView,
    FilingView,
    ParseRunView,
    ReadServiceError,
    SectionView,
    StatementView,
    TableView,
)

app = FastAPI(title="Finance Data Collector Read API", version="1.0.0")

ViewT = TypeVar("ViewT", bound=BaseModel)


def _read(operation: Callable[[], ViewT]) -> ViewT:
    try:
        return operation()
    except ReadServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail()) from error


@app.get("/api/v1/companies/{ticker}", response_model=CompanyView)
def company(ticker: str) -> CompanyView:
    return _read(lambda: read_service.get_company(ticker))


@app.get("/api/v1/companies/{ticker}/filings", response_model=FilingListView)
def company_filings(
    ticker: str,
    form: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FilingListView:
    return _read(lambda: read_service.list_filings(ticker, form, limit, offset))


@app.get("/api/v1/filings/{accession}", response_model=FilingView)
def filing(accession: str) -> FilingView:
    return _read(lambda: read_service.get_filing(accession))


@app.get("/api/v1/filings/{accession}/statements", response_model=StatementView)
def filing_statements(accession: str, statement_type: str) -> StatementView:
    return _read(lambda: read_service.get_statement(accession, statement_type))


@app.get("/api/v1/filings/{accession}/facts", response_model=FactView)
def filing_facts(accession: str, concept: str | None = None) -> FactView:
    return _read(lambda: read_service.get_facts(accession, concept))


@app.get("/api/v1/filings/{accession}/sections/{section_type}", response_model=SectionView)
def filing_section(accession: str, section_type: str) -> SectionView:
    return _read(lambda: read_service.get_section(accession, section_type))


@app.get("/api/v1/filings/{accession}/tables", response_model=TableView)
def filing_tables(accession: str, table_type: str | None = None) -> TableView:
    return _read(lambda: read_service.get_tables(accession, table_type))


@app.get(
    "/api/v1/filings/{accession}/evidence/{evidence_id}",
    response_model=EvidenceView,
)
def filing_evidence(accession: str, evidence_id: str) -> EvidenceView:
    return _read(lambda: read_service.get_evidence(accession, evidence_id))


@app.get("/api/v1/parse-runs/{run_id}", response_model=ParseRunView)
def parse_run(run_id: str) -> ParseRunView:
    return _read(lambda: read_service.get_parse_run(run_id))
