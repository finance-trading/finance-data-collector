"""AI company catalog, database coverage merge, and visualization payloads."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from fdc.ai_layers import validate_universe
from fdc.config import get_settings
from fdc.data_files import CATALOG_PATH, GRAPH_PATH, LAYERS_PATH
from fdc.db import SessionLocal
from fdc.models import Filing, FilingParse, Issuer
from fdc.read_service import ReadServiceError

IngestionStatus = Literal["parsed", "failed", "unavailable", "not_ingested"]


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


class CompanyDirectoryView(BaseModel):
    query: str | None
    layer: str | None
    segment: str | None
    ingestion_status: IngestionStatus | None
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


def _database_summaries(
    session: Session,
) -> dict[str, _IssuerSummary]:
    parser_version = get_settings().parser_version
    rows = session.execute(
        select(Issuer, Filing, FilingParse)
        .outerjoin(Filing, Filing.issuer_id == Issuer.id)
        .outerjoin(
            FilingParse,
            and_(
                FilingParse.filing_id == Filing.id,
                FilingParse.parser_version == parser_version,
            ),
        )
        .where(Issuer.ticker_hint.is_not(None))
    ).all()

    by_issuer: dict[Any, dict[str, Any]] = {}
    for issuer, filing, result in rows:
        state = by_issuer.setdefault(
            issuer.id,
            {"issuer": issuer, "filings": {}, "parses": {}},
        )
        if filing is None:
            continue
        state["filings"][filing.id] = filing
        if result is not None:
            current = state["parses"].get(filing.id)
            if current is None or _parse_key(result) > _parse_key(current):
                state["parses"][filing.id] = result

    canonical: dict[str, tuple[tuple[date, datetime, str], _IssuerSummary]] = {}
    for state in by_issuer.values():
        issuer: Issuer = state["issuer"]
        filings: list[Filing] = list(state["filings"].values())
        latest = max(
            filings,
            key=lambda filing: (
                filing.filing_date or date.min,
                filing.accession_number,
            ),
            default=None,
        )
        latest_parse = state["parses"].get(latest.id) if latest is not None else None
        summary = _IssuerSummary(
            cik=issuer.cik,
            latest_filing_date=latest.filing_date if latest is not None else None,
            latest_filing_status=latest_parse.status if latest_parse is not None else None,
            filing_count=len(filings),
        )
        key = (
            latest.filing_date if latest is not None and latest.filing_date else date.min,
            latest.created_at if latest is not None else issuer.created_at,
            issuer.cik,
        )
        ticker = (issuer.ticker_hint or "").upper()
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


def list_companies(
    query: str | None,
    layer: str | None,
    segment: str | None,
    ingestion_status: IngestionStatus | None,
    limit: int,
    offset: int,
    *,
    catalog_path: Path | str | None = None,
    session_factory: Callable[..., Session] = SessionLocal,
) -> CompanyDirectoryView:
    """Merge catalog companies with persisted coverage, then filter and page."""

    catalog = load_catalog(catalog_path)
    layer_names = {item.id: item.name for item in catalog.layers}
    with session_factory() as session:
        summaries = _database_summaries(session)

    needle = query.strip().casefold() if query and query.strip() else None
    normalized_layer = layer.strip() if layer and layer.strip() else None
    normalized_segment = segment.strip() if segment and segment.strip() else None
    companies: list[CompanyDirectoryItem] = []
    for company in catalog.companies:
        summary = summaries.get(company.ticker.upper())
        status = _status(summary)
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
            )
        )

    return CompanyDirectoryView(
        query=query.strip() if query and query.strip() else None,
        layer=normalized_layer,
        segment=normalized_segment,
        ingestion_status=ingestion_status,
        limit=limit,
        offset=offset,
        total=len(companies),
        companies=companies[offset : offset + limit],
    )


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
