"""FastAPI application serving filing parse results and quote refreshes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.staticfiles import StaticFiles

from fdc import catalog, funnel, read_service
from fdc.catalog import (
    CatalogLayerListView,
    CompanyDirectoryView,
    IngestionStatus,
    Order,
    QuotesView,
    SortKey,
)
from fdc.db import SessionLocal
from fdc.models import ResearchAnnotation
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


class FunnelOverrideIn(BaseModel):
    """Set or reset one company's manual tier. ``tier=None`` clears the override.

    ``note=None`` keeps the existing note so a tier-only edit does not clobber it.
    """

    ticker: str
    tier: int | None
    note: str | None = None


def _require_local_write(request: Request) -> None:
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
    ):
        raise HTTPException(status_code=403, detail="Edits require a local connection")
    origin = request.headers.get("origin")
    if origin is not None and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="Edits require the same origin")


@app.post("/api/v1/funnel/overrides")
def set_funnel_override(payload: FunnelOverrideIn, request: Request) -> dict[str, Any]:
    """Persist a manual funnel tier to ``config/funnel_overrides.json``.

    The tier config write edits the same file the funnel CLI and tier badge
    read from, so the change is live everywhere on the next tier
    resolution. Returns the company's resulting (auto-or-manual) tier.
    """
    _require_local_write(request)

    ticker = payload.ticker.upper()
    known = {company.ticker.upper() for company in catalog.load_catalog().companies}
    if ticker not in known:
        raise HTTPException(status_code=404, detail=f"{ticker} is not in the AI universe")

    if payload.tier is None:
        funnel.remove_override(ticker)
    else:
        if type(payload.tier) is not int or payload.tier not in (1, 2, 3):
            raise HTTPException(
                status_code=400, detail="tier must be 1, 2 or 3 (null resets to auto)"
            )
        existing = funnel.load_overrides().get(ticker, {})
        note = payload.note if payload.note is not None else existing.get("note", "")
        if not note.strip():
            raise HTTPException(status_code=400, detail="Manual tier requires a reason")
        funnel.upsert_override(ticker, payload.tier, note)

    resolved = catalog.funnel_tier_index().get(ticker, {})
    return {"ticker": ticker, **resolved}


class AnnotationRange(BaseModel):
    low: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    high: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_range(self) -> "AnnotationRange":
        if (self.low is None) != (self.high is None):
            raise ValueError("Both range endpoints are required")
        if self.low is not None and self.low > self.high:
            raise ValueError("Range low must not exceed high")
        return self


class AnnotationWatchItem(BaseModel):
    priority: Literal[1, 2, 3]
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Watch item must not be blank")
        return value.strip()


class ResearchAnnotationIn(BaseModel):
    observation_range: AnnotationRange | None = None
    entry_range: AnnotationRange | None = None
    add_range: AnnotationRange | None = None
    reduce_range: AnnotationRange | None = None
    watch_items: list[AnnotationWatchItem] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def has_changes(self) -> "ResearchAnnotationIn":
        fields = {"observation_range", "entry_range", "add_range", "reduce_range", "watch_items"}
        if not self.model_fields_set or any(
            field not in fields or getattr(self, field) is None
            for field in self.model_fields_set
        ):
            raise ValueError("Provide one or more non-null annotation fields")
        return self


@app.post("/api/v1/research/annotations/{ticker}")
def save_research_annotation(
    ticker: str, payload: ResearchAnnotationIn, request: Request
) -> dict[str, Any]:
    _require_local_write(request)
    key = ticker.upper()
    if key not in {company.ticker.upper() for company in catalog.load_catalog().companies}:
        raise HTTPException(status_code=404, detail=f"{key} is not in the AI universe")
    with SessionLocal() as session:
        with session.begin():
            row = session.get(ResearchAnnotation, key)
            if row is None:
                defaults = funnel.tier_watch_items(
                    catalog.funnel_tier_index().get(key, {}).get("tier")
                )
                row = ResearchAnnotation(ticker=key, watch_items=defaults)
                session.add(row)
            for field, prefix in (
                ("observation_range", "observe"),
                ("entry_range", "entry"),
                ("add_range", "add"),
                ("reduce_range", "reduce"),
            ):
                band = getattr(payload, field)
                if band is not None:
                    setattr(row, f"{prefix}_low", band.low)
                    setattr(row, f"{prefix}_high", band.high)
            if payload.watch_items is not None:
                row.watch_items = [item.model_dump() for item in payload.watch_items]
    return {"ticker": key, **payload.model_dump(exclude_none=True), "annotation_saved": True}


@app.post("/api/v1/quotes/refresh", response_model=QuotesView)
def refresh_quotes() -> QuotesView:
    """Force a Yahoo Finance re-fetch and serve the rewritten cache.

    Runs in FastAPI's thread pool, so the ~30 s yfinance fetch does not block the
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
