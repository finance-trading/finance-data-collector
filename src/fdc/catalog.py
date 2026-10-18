"""AI company catalog, database coverage merge, and visualization payloads."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fdc.ai_layers import validate_universe
from fdc.config import get_settings
from fdc.data_files import CATALOG_PATH, GRAPH_PATH, LAYERS_PATH, QUOTES_PATH
from fdc.db import SessionLocal
from fdc.models import Filing, FilingParse, Issuer
from fdc.read_service import ReadServiceError

IngestionStatus = Literal["parsed", "failed", "unavailable", "not_ingested"]
SortKey = Literal[
    "market_cap", "change_pct", "week_change_pct", "change_52w_pct"
]
Order = Literal["desc", "asc"]


class CatalogCompany(BaseModel):
    ticker: str
    name: str
    sector: str
    industry: str
    layer: str
    segment: str
    description: str
    also_in: list[str] = Field(default_factory=list)


class CatalogLayer(BaseModel):
    id: str
    name: str
    name_en: str = ""
    summary: str = ""
    segments: list[str]


class CatalogView(BaseModel):
    companies: list[CatalogCompany]
    layers: list[CatalogLayer]


class CatalogSegmentView(BaseModel):
    name: str
    count: int


class CatalogLayerView(BaseModel):
    id: str
    name: str
    name_en: str
    summary: str
    count: int
    segments: list[CatalogSegmentView]


class CatalogLayerListView(BaseModel):
    total_companies: int
    layers: list[CatalogLayerView]


class CompanyDirectoryItem(CatalogCompany):
    layer_name: str
    cik: str | None = None
    latest_filing_date: date | None = None
    latest_filing_status: str | None = None
    ingestion_status: IngestionStatus
    filing_count: int
    research_available: bool
    price: float | None = None
    market_cap: int | None = None
    change_pct: float | None = None
    week_change_pct: float | None = None
    week_rise_pct: float | None = None
    change_52w_pct: float | None = None
    rise_52w_pct: float | None = None
    pe: float | None = None
    eps_ttm: float | None = None
    forward_pe: float | None = None
    forward_eps: float | None = None
    quote_as_of: date | None = None


class CompanyDirectoryView(BaseModel):
    query: str | None
    layer: str | None
    segment: str | None
    ingestion_status: IngestionStatus | None
    sort_by: SortKey | None = None
    order: Order = "desc"
    limit: int
    offset: int
    total: int
    companies: list[CompanyDirectoryItem]


class _IssuerSummary(BaseModel):
    cik: str
    latest_filing_date: date | None
    latest_filing_status: str | None
    filing_count: int


def load_catalog(path: Path | str | None = None) -> CatalogView:
    """Load and validate the ordered curated AI company universe."""

    resolved = Path(path) if path is not None else CATALOG_PATH
    payload = json.loads(resolved.read_text())
    companies = payload["companies"]
    layers = payload["layers"]
    validate_universe(companies, layers)
    return CatalogView.model_validate({"companies": companies, "layers": layers})


def list_layers(path: Path | str | None = None) -> CatalogLayerListView:
    """Return the declared taxonomy with company counts in source order."""

    catalog = load_catalog(path)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for company in catalog.companies:
        counts[(company.layer, company.segment)] += 1
    return CatalogLayerListView(
        total_companies=len(catalog.companies),
        layers=[
            CatalogLayerView(
                id=layer.id,
                name=layer.name,
                name_en=layer.name_en,
                summary=layer.summary,
                count=sum(counts[(layer.id, segment)] for segment in layer.segments),
                segments=[
                    CatalogSegmentView(name=segment, count=counts[(layer.id, segment)])
                    for segment in layer.segments
                ],
            )
            for layer in catalog.layers
        ],
    )


def _parse_key(result: FilingParse) -> tuple[int, datetime]:
    current_success = result.is_current and result.status == "success"
    return (1 if current_success else 0, result.created_at)


def _load_quotes() -> tuple[
    dict[str, dict[str, float | int | None]], date | None, str | None
]:
    """Return cached quotes, the session quote date, and the raw refresh stamp."""

    if not QUOTES_PATH.exists():
        return {}, None, None
    try:
        payload = json.loads(QUOTES_PATH.read_text())
        quotes = payload.get("quotes", {})
        generated_at = payload.get("generated_at")
        # The daily job runs after the US close, so the UTC stamp lands on the
        # next calendar day.  Report the local session date, not the UTC one.
        as_of = (
            datetime.fromisoformat(generated_at).astimezone().date()
            if generated_at
            else None
        )
        return quotes, as_of, generated_at
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return {}, None, None


def _database_summaries(
    session: Session,
) -> dict[str, _IssuerSummary]:
    parser_version = get_settings().parser_version

    issuer_rows = session.execute(
        select(Issuer.id, Issuer.cik, Issuer.ticker_hint, Issuer.created_at)
        .where(Issuer.ticker_hint.is_not(None))
    ).all()

    # Filing counts per issuer — grouped, no cross-join.
    count_rows = session.execute(
        select(Filing.issuer_id, func.count(Filing.id))
        .group_by(Filing.issuer_id)
    ).all()
    counts: dict[uuid.UUID, int] = {
        issuer_id: count for issuer_id, count in count_rows
    }

    # Latest filing per issuer, chosen exactly as the reference implementation
    # did: greatest (filing_date, accession_number) with a NULL filing_date
    # treated as the minimum. One window pass over `filing` (no join product).
    latest_cte = (
        select(
            Filing.issuer_id.label("issuer_id"),
            Filing.id.label("filing_id"),
            Filing.filing_date.label("filing_date"),
            Filing.created_at.label("filing_created_at"),
            func.row_number()
            .over(
                partition_by=Filing.issuer_id,
                order_by=[
                    Filing.filing_date.desc().nulls_last(),
                    Filing.accession_number.desc(),
                ],
            )
            .label("rn"),
        )
        .cte("latest_filings")
    )
    latest_rows = session.execute(
        select(
            latest_cte.c.issuer_id,
            latest_cte.c.filing_id,
            latest_cte.c.filing_date,
            latest_cte.c.filing_created_at,
        ).where(latest_cte.c.rn == 1)
    ).all()
    latest: dict[uuid.UUID, tuple[date | None, datetime, uuid.UUID]] = {
        issuer_id: (filing_date, filing_created_at, filing_id)
        for issuer_id, filing_id, filing_date, filing_created_at in latest_rows
    }

    # The chosen parse status for each latest filing: the parse with the
    # greatest _parse_key among that filing's current-version parses.
    latest_filing_ids = [entry[2] for entry in latest.values()]
    parse_status: dict[uuid.UUID, str] = {}
    if latest_filing_ids:
        parse_rows = session.execute(
            select(
                FilingParse.filing_id,
                FilingParse.status,
                FilingParse.is_current,
                FilingParse.created_at,
            )
            .where(
                FilingParse.filing_id.in_(latest_filing_ids),
                FilingParse.parser_version == parser_version,
            )
        ).all()
        by_filing: dict[uuid.UUID, tuple[tuple[int, datetime], str]] = {}
        for filing_id, status, is_current, created_at in parse_rows:
            key = (int(is_current and status == "success"), created_at)
            current = by_filing.get(filing_id)
            if current is None or key > current[0]:
                by_filing[filing_id] = (key, status)
        parse_status = {filing_id: entry[1] for filing_id, entry in by_filing.items()}

    canonical: dict[str, tuple[tuple[date, datetime, str], _IssuerSummary]] = {}
    for issuer_id, cik, ticker_hint, issuer_created_at in issuer_rows:
        filing_date, filing_created_at, filing_id = latest.get(
            issuer_id, (None, None, None)
        )
        summary = _IssuerSummary(
            cik=cik,
            latest_filing_date=filing_date,
            latest_filing_status=parse_status.get(filing_id) if filing_id else None,
            filing_count=counts.get(issuer_id, 0),
        )
        key = (
            filing_date or date.min,
            filing_created_at if filing_id is not None else issuer_created_at,
            cik,
        )
        ticker = (ticker_hint or "").upper()
        if ticker not in canonical or key > canonical[ticker][0]:
            canonical[ticker] = (key, summary)
    return {ticker: summary for ticker, (_, summary) in canonical.items()}


def _status(summary: _IssuerSummary | None) -> IngestionStatus:
    if summary is None or summary.filing_count == 0:
        return "not_ingested"
    if summary.latest_filing_status == "success":
        return "parsed"
    if summary.latest_filing_status == "failed":
        return "failed"
    return "unavailable"


def _quote_sort_key(
    item: CompanyDirectoryItem, sort_by: SortKey, descending: bool
) -> tuple[bool, float]:
    """Sort by a quote field, keeping companies with no quote last."""

    value: float | int | None = getattr(item, sort_by)
    if value is None:
        return (True, 0.0)
    return (False, -value if descending else value)


def list_companies(
    query: str | None,
    layer: str | None,
    segment: str | None,
    ingestion_status: IngestionStatus | None,
    limit: int,
    offset: int,
    *,
    sort_by: SortKey | None = None,
    order: Order = "desc",
    catalog_path: Path | str | None = None,
    session_factory: Callable[..., Session] = SessionLocal,
) -> CompanyDirectoryView:
    """Merge catalog companies with persisted coverage, then filter and page."""

    catalog = load_catalog(catalog_path)
    layer_names = {item.id: item.name for item in catalog.layers}
    quotes, quote_as_of, _ = _load_quotes()
    with session_factory() as session:
        summaries = _database_summaries(session)

    needle = query.strip().casefold() if query and query.strip() else None
    normalized_layer = layer.strip() if layer and layer.strip() else None
    normalized_segment = segment.strip() if segment and segment.strip() else None
    companies: list[CompanyDirectoryItem] = []
    for company in catalog.companies:
        ticker = company.ticker.upper()
        summary = summaries.get(ticker)
        status = _status(summary)
        quote = quotes.get(ticker)
        if (
            needle
            and needle not in company.ticker.casefold()
            and needle not in company.name.casefold()
        ):
            continue
        if normalized_layer and company.layer != normalized_layer:
            continue
        if normalized_segment and company.segment != normalized_segment:
            continue
        if ingestion_status and status != ingestion_status:
            continue
        companies.append(
            CompanyDirectoryItem(
                **company.model_dump(),
                layer_name=layer_names[company.layer],
                cik=summary.cik if summary else None,
                latest_filing_date=summary.latest_filing_date if summary else None,
                latest_filing_status=summary.latest_filing_status if summary else None,
                ingestion_status=status,
                filing_count=summary.filing_count if summary else 0,
                research_available=bool(summary and summary.filing_count),
                price=quote.get("price") if quote else None,
                market_cap=quote.get("market_cap") if quote else None,
                change_pct=quote.get("change_pct") if quote else None,
                week_change_pct=quote.get("week_change_pct") if quote else None,
                week_rise_pct=quote.get("week_rise_pct") if quote else None,
                change_52w_pct=quote.get("change_52w_pct") if quote else None,
                rise_52w_pct=quote.get("rise_52w_pct") if quote else None,
                pe=quote.get("pe") if quote else None,
                eps_ttm=quote.get("eps_ttm") if quote else None,
                forward_pe=quote.get("forward_pe") if quote else None,
                forward_eps=quote.get("forward_eps") if quote else None,
                quote_as_of=quote_as_of,
            )
        )

    if sort_by:
        # Descending by default: biggest caps and biggest daily moves first.
        # Sort before slicing so pagination walks a globally ordered list.
        companies.sort(
            key=lambda item: _quote_sort_key(
                item, sort_by, descending=(order == "desc")
            )
        )

    return CompanyDirectoryView(
        query=query.strip() if query and query.strip() else None,
        layer=normalized_layer,
        segment=normalized_segment,
        ingestion_status=ingestion_status,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
        total=len(companies),
        companies=companies[offset : offset + limit],
    )


class QuotesView(BaseModel):
    generated_at: str | None
    quotes: dict[str, dict[str, float | int | None]]


def read_quotes() -> QuotesView:
    """Return the cached quotes as a standalone payload; empty when absent."""

    quotes, _, generated_at = _load_quotes()
    return QuotesView(generated_at=generated_at, quotes=quotes)


def read_visualization(name: Literal["graph", "layers"]) -> dict[str, Any]:
    """Load one generated visualization or return an explicit unavailable state."""

    path = GRAPH_PATH if name == "graph" else LAYERS_PATH
    if not path.exists():
        raise ReadServiceError(
            409,
            "unavailable",
            f"{name} visualization has not been generated",
            {"artifact": name, "regenerate": f"uv run python -m fdc.{name}"},
        )
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReadServiceError(
            409,
            "unavailable",
            f"{name} visualization could not be read",
            {"artifact": name, "error": type(error).__name__},
        ) from error
