"""FastAPI application serving filing parse results and quote refreshes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles

from fdc import catalog, read_service
from fdc.catalog import (
    CatalogLayerListView,
    CompanyDirectoryView,
    IngestionStatus,
    Order,
    QuotesView,
    SortKey,
)
from fdc.quotes import write_quotes
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

logger = logging.getLogger(__name__)

ViewT = TypeVar("ViewT", bound=BaseModel)


def _read(operation: Callable[[], ViewT]) -> ViewT:
    try:
        return operation()
    except ReadServiceError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail()) from error


@app.get("/api/v1/companies", response_model=CompanyDirectoryView)
def companies(
    query: str | None = None,
    layer: str | None = None,
    segment: str | None = None,
    ingestion_status: Annotated[IngestionStatus | None, Query()] = None,
    sort_by: Annotated[SortKey | None, Query()] = None,
    order: Order = "desc",
    funnel_tier: Annotated[
        int | None,
        Query(ge=1, le=3, description="Funnel tier: 1 core, 2 major, 3 watch"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyDirectoryView:
    return _read(
        lambda: catalog.list_companies(
            query,
            layer,
            segment,
            ingestion_status,
            limit,
            offset,
            sort_by=sort_by,
            order=order,
            funnel_tier=funnel_tier,
        )
    )


@app.get("/api/v1/catalog/layers", response_model=CatalogLayerListView)
def catalog_layers() -> CatalogLayerListView:
    return _read(catalog.list_layers)


@app.get("/api/v1/quotes", response_model=QuotesView)
def quotes() -> QuotesView:
    return _read(catalog.read_quotes)


@app.get("/api/v1/funnel/tiers")
def funnel_tiers() -> dict[str, Any]:
    """TICKER -> resolved funnel tier, live off catalog + quotes + overrides.

    Serves the layers visualization, which badges each company with the same
    tier the directory page shows rather than a stale baked snapshot.
    """
    return catalog.funnel_tier_index()


@app.post("/api/v1/quotes/refresh", response_model=QuotesView)
def refresh_quotes() -> QuotesView:
    """Force a Yahoo Finance re-fetch and serve the rewritten cache.

    The only write on this app; everything else stays read-only.  Runs in
    FastAPI's thread pool, so the ~30 s yfinance fetch does not block the
    event loop.  A failed fetch keeps the previous cache and reports 502 so the
    page can say so instead of silently rendering empty prices.
    """

    try:
        write_quotes(force=True)
    except Exception as exc:
        logger.exception("quote refresh failed")
        raise HTTPException(
            status_code=502, detail="Yahoo Finance refresh failed — prices unchanged"
        ) from exc
    return _read(catalog.read_quotes)


@app.get("/api/v1/visualizations/{name}")
def visualization(name: Literal["graph", "layers"]) -> dict[str, Any]:
    return _read(lambda: catalog.read_visualization(name))


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


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIST, html=True, check_dir=False),
    name="frontend",
)
