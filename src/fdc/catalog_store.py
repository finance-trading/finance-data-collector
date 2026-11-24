"""DB-backed readers for the migrated business data, with file fallback.

After migration 0014 the relational store is the runtime source of truth for
the catalog, funnel overrides and quality inputs; the JSON/CSV files remain
the import source and rollback baseline.  Every reader here is DB-first and
returns ``None`` when the relevant DB table is empty, so callers fall back
to the checked-in files (unit tests and fresh checkouts need no import run).

This module must stay free of imports from :mod:`fdc.catalog`,
:mod:`fdc.funnel` and :mod:`fdc.quality_facts_external` to avoid cycles; it
only touches models, the DB helpers and the canonical paths.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from fdc.data_files import CATALOG_PATH, DATA_ROOT
from fdc.db import get_session_factory
from fdc.models import (
    AiCompany,
    AiLayer,
    AiSegment,
    FunnelOverride,
    QualityAnnualFact,
    QualityInputBatch,
    QualityPeer,
)
from sqlalchemy.exc import DBAPIError

#: A store that cannot be queried (migration 0014 not applied yet, unreachable
#: server) is treated as empty so readers fall back to the checked-in files
#: instead of crashing the request.
_FALLBACK_ERRORS = (DBAPIError,)

QUALITY_DIR = DATA_ROOT / "company_quality"

FACT_COLUMNS = (
    "cik", "concept", "label", "value", "numeric_value", "unit", "period_type",
    "period_start", "period_end", "fiscal_year", "fiscal_period", "accession",
    "filing_date", "form_type", "statement_type", "taxonomy", "scale",
    "data_quality", "is_audited", "confidence_score", "period_days",
    "period_shape", "metric",
)
PEER_COLUMNS = (
    "source_symbol", "canonical_symbol", "company_name", "gics_sector",
    "gics_sub_industry", "cik", "date_added",
)
_NUMERIC_FACT_COLUMNS = ("value", "numeric_value", "confidence_score", "fiscal_year", "period_days")


def _session() -> Session:
    return get_session_factory()()


def load_catalog_dicts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """The catalog as ``(companies, layers)`` raw-dict lists, or ``None`` when
    the ``ai_company`` table is empty or the store cannot be queried (fall back
    to the JSON file)."""

    session = _session()
    try:
        layers = session.execute(select(AiLayer).order_by(AiLayer.position)).scalars().all()
        if not layers:
            return None
        companies = session.execute(select(AiCompany).order_by(AiCompany.position)).scalars().all()
        if not companies:
            return None
        segments = session.execute(
            select(AiSegment).order_by(AiSegment.layer_id, AiSegment.position)
        ).scalars().all()
        segments_by_layer: dict[str, list[str]] = {}
        for segment in segments:
            segments_by_layer.setdefault(segment.layer_id, []).append(segment.name)
        layers_dicts = [
            {
                "id": layer.id, "name": layer.name, "name_en": layer.name_en,
                "summary": layer.summary, "segments": segments_by_layer.get(layer.id, []),
            }
            for layer in layers
        ]
        companies_dicts = [
            {
                "ticker": company.ticker, "name": company.name, "sector": company.sector,
                "industry": company.industry, "layer": company.layer_id,
                "segment": company.segment, "also_in": company.also_in or [],
                "description": company.description,
            }
            for company in companies
        ]
        return companies_dicts, layers_dicts
    except _FALLBACK_ERRORS:
        return None
    finally:
        session.close()


def load_catalog_payload() -> dict[str, Any]:
    """The full ``ai_companies.json`` payload shape (``{"companies", "layers"}``)
    from the DB, falling back to the file; raises ``FileNotFoundError`` when
    neither has data."""

    dicts = load_catalog_dicts()
    if dicts is not None:
        companies, layers = dicts
        return {"companies": companies, "layers": layers}
    payload = json.loads(CATALOG_PATH.read_text())
    return {"companies": payload["companies"], "layers": payload["layers"]}


def load_overrides_dicts() -> dict[str, dict[str, Any]] | None:
    """Manual funnel-tier overrides from the DB, or ``None`` when the table is
    empty (fall back to ``config/funnel_overrides.json``)."""

    session = _session()
    try:
        rows = session.execute(select(FunnelOverride).order_by(FunnelOverride.ticker)).scalars().all()
        if not rows:
            return None
        return {row.ticker: {"tier": row.tier, "note": row.note or ""} for row in rows}
    except _FALLBACK_ERRORS:
        return None
    finally:
        session.close()


def upsert_override_db(ticker: str, tier: int, note: str) -> None:
    """Insert or update one manual tier in the ``funnel_override`` table."""

    session = _session()
    try:
        row = session.get(FunnelOverride, ticker)
        if row is None:
            session.add(FunnelOverride(ticker=ticker, tier=tier, note=note))
        else:
            row.tier = tier
            row.note = note
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def remove_override_db(ticker: str) -> bool:
    """Drop one manual tier; returns whether a row was removed."""

    session = _session()
    try:
        result = session.execute(delete(FunnelOverride).where(FunnelOverride.ticker == ticker))
        session.commit()
        return result.rowcount > 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _latest_batch(kind: str) -> QualityInputBatch | None:
    session = _session()
    try:
        return session.execute(
            select(QualityInputBatch)
            .where(QualityInputBatch.kind == kind)
            .order_by(QualityInputBatch.created_at.desc(), QualityInputBatch.id.desc())
            .limit(1)
        ).scalars().one_or_none()
    except _FALLBACK_ERRORS:
        return None
    finally:
        session.close()


def _frame_from_batch(batch: QualityInputBatch) -> pd.DataFrame:
    session = _session()
    try:
        columns = [getattr(QualityAnnualFact, column) for column in FACT_COLUMNS]
        select_stmt = (
            select(*columns)
            .where(QualityAnnualFact.batch_id == batch.id)
            .order_by(QualityAnnualFact.id)
        )
        data: dict[str, list[Any]] = {column: [] for column in FACT_COLUMNS}
        for row in session.execute(select_stmt).yield_per(20000):
            for column, value in zip(FACT_COLUMNS, row):
                data[column].append(value)
        frame = pd.DataFrame(data)
        for column in _NUMERIC_FACT_COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame
    except _FALLBACK_ERRORS:
        return pd.DataFrame()
    finally:
        session.close()


def load_quality_facts_frame() -> pd.DataFrame | None:
    """The newest ``annual_facts`` batch as a pandas frame matching the CSV
    layout, or ``None`` when no batch has been imported."""

    batch = _latest_batch("annual_facts")
    if batch is None:
        return None
    frame = _frame_from_batch(batch)
    return frame if not frame.empty else None


def load_quality_universe_frame() -> pd.DataFrame | None:
    """The newest ``peer_universe`` batch as a pandas frame, or ``None``."""

    batch = _latest_batch("peer_universe")
    if batch is None:
        return None
    session = _session()
    try:
        columns = [getattr(QualityPeer, column) for column in PEER_COLUMNS]
        rows = session.execute(
            select(*columns)
            .where(QualityPeer.batch_id == batch.id)
            .order_by(QualityPeer.id)
        ).all()
        data = {column: [getattr(row, column) for row in rows] for column in PEER_COLUMNS}
        frame = pd.DataFrame(data)
        if frame.empty:
            return None
        frame["date_added"] = frame["date_added"].apply(
            lambda value: value.isoformat() if value is not None else None
        )
        return frame
    except _FALLBACK_ERRORS:
        return None
    finally:
        session.close()
