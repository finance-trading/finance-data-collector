"""One-shot import of file-based business data into the relational store.

Sources (kept on disk as the import source and rollback baseline):

* ``data/ai_companies.json``          -> ``ai_layer`` / ``ai_segment`` / ``ai_company``
* ``config/funnel_overrides.json``    -> ``funnel_override``
* ``data/company_quality/*.csv.gz``   -> ``quality_input_batch`` /
  ``quality_annual_fact`` / ``quality_peer`` (provenance from
  ``source_manifest.json``)

Every import is idempotent and transactional: the target rows for one source
are replaced wholesale.  Source files are never modified.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from fdc.catalog import load_catalog
from fdc.data_files import CATALOG_PATH, PROJECT_ROOT
from fdc.db import session_scope
from fdc.funnel import OVERRIDES_PATH, load_overrides
from fdc.models import (
    AiCompany,
    AiLayer,
    AiSegment,
    FunnelOverride,
    QualityAnnualFact,
    QualityInputBatch,
    QualityPeer,
)
from fdc.models import _now

QUALITY_DIR = PROJECT_ROOT / "data" / "company_quality"
MANIFEST_PATH = QUALITY_DIR / "source_manifest.json"
# PostgreSQL caps a statement at 65535 bind parameters; keep rows x columns
# well under that (annual facts carry ~24 columns -> 1000 rows ~ 24k params).
_CHUNK = 1000

_FACT_COLUMNS = (
    "cik", "concept", "label", "value", "numeric_value", "unit", "period_type",
    "period_start", "period_end", "fiscal_year", "fiscal_period", "accession",
    "filing_date", "form_type", "statement_type", "taxonomy", "scale",
    "data_quality", "is_audited", "confidence_score", "period_days", "period_shape",
    "metric",
)
_PEER_COLUMNS = (
    "source_symbol", "canonical_symbol", "company_name", "gics_sector",
    "gics_sub_industry", "cik", "date_added",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_catalog(session: Session, path: Path | str = CATALOG_PATH) -> dict[str, int]:
    """Replace the ``ai_*`` tables with the catalog at ``path``."""

    catalog = load_catalog(path)
    session.execute(delete(AiCompany))
    session.execute(delete(AiSegment))
    session.execute(delete(AiLayer))
    session.add_all(
        AiLayer(
            id=layer.id, name=layer.name, name_en=layer.name_en,
            summary=layer.summary, position=position,
        )
        for position, layer in enumerate(catalog.layers)
    )
    session.flush()
    session.add_all(
        AiSegment(layer_id=layer.id, name=segment, position=index)
        for layer in catalog.layers
        for index, segment in enumerate(layer.segments)
    )
    session.flush()
    session.add_all(
        AiCompany(
            ticker=company.ticker.upper(), name=company.name, sector=company.sector,
            industry=company.industry, layer_id=company.layer, segment=company.segment,
            also_in=company.also_in, description=company.description, position=position,
        )
        for position, company in enumerate(catalog.companies)
    )
    session.flush()
    return {
        "layers": len(catalog.layers),
        "segments": sum(len(layer.segments) for layer in catalog.layers),
        "companies": len(catalog.companies),
    }


def import_funnel_overrides(session: Session, path: Path | str = OVERRIDES_PATH) -> int:
    """Replace the ``funnel_override`` rows with the manual tiers in ``path``."""

    overrides = load_overrides(path)
    session.execute(delete(FunnelOverride))
    session.add_all(
        FunnelOverride(ticker=ticker, tier=value["tier"], note=value.get("note", ""))
        for ticker, value in overrides.items()
    )
    session.flush()
    return len(overrides)


def _load_gz_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _fact_row(batch_id: str, row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {"batch_id": batch_id}
    for column in _FACT_COLUMNS:
        raw = row.get(column, "")
        if raw in ("", None):
            out[column] = None
            continue
        if column in ("value", "numeric_value", "confidence_score"):
            out[column] = Decimal(raw)
        elif column in ("fiscal_year", "period_days"):
            out[column] = int(float(raw))
        elif column in ("period_start", "period_end", "filing_date"):
            out[column] = date.fromisoformat(raw)
        elif column == "is_audited":
            out[column] = raw.strip().lower() == "true"
        else:
            out[column] = raw
    return out


def _peer_row(batch_id: str, row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "batch_id": batch_id,
        **{col: (row.get(col) or None) for col in _PEER_COLUMNS},
    }
    if out.get("date_added"):
        out["date_added"] = date.fromisoformat(out["date_added"])
    return out


def import_quality_inputs(
    session: Session, manifest: Path | str = MANIFEST_PATH
) -> dict[str, str]:
    """Import the facts + peer-universe CSVs named in ``manifest``.

    Returns ``{"annual_facts": batch_id, "peer_universe": batch_id}``.
    """

    payload = json.loads(Path(manifest).read_text())
    results: dict[str, str] = {}
    for kind, manifest_key, source_key in (
        ("annual_facts", "facts_sha256", "facts_path"),
        ("peer_universe", "peer_universe_sha256", "peer_universe_path"),
    ):
        source_path = Path(payload[source_key])
        if not source_path.is_absolute():
            # The checked-in manifest stores project-root-relative paths.
            source_path = PROJECT_ROOT / source_path
        expected = payload.get(manifest_key)
        actual = _sha256(source_path)
        if expected is not None and actual != expected:
            raise ValueError(f"{kind}: file sha256 {actual} != manifest {expected}")

        batch_id = f"{kind}:{source_path.name}"
        rows = _load_gz_csv(source_path)
        session.execute(delete(QualityAnnualFact).where(QualityAnnualFact.batch_id == batch_id))
        session.execute(delete(QualityPeer).where(QualityPeer.batch_id == batch_id))

        batch = session.scalars(
            select(QualityInputBatch).where(QualityInputBatch.id == batch_id)
        ).one_or_none()
        values = dict(
            kind=kind,
            source=str(source_path),
            sha256=actual,
            row_count=len(rows),
            rating_cutoff=date.fromisoformat(payload["rating_cutoff"])
            if payload.get("rating_cutoff")
            else None,
            rule_version=payload.get("rule_version"),
            semantic_policy=payload.get("semantic_policy"),
            created_at=_now(),
        )
        if batch is None:
            session.add(QualityInputBatch(id=batch_id, **values))
        else:
            for key, value in values.items():
                setattr(batch, key, value)
        session.flush()  # batch row must exist before its fact/peer rows

        if kind == "annual_facts":
            values = [_fact_row(batch_id, row) for row in rows]
            for start in range(0, len(values), _CHUNK):
                session.execute(insert(QualityAnnualFact).values(values[start : start + _CHUNK]))
        else:
            session.execute(
                insert(QualityPeer).values([_peer_row(batch_id, row) for row in rows])
            )
        session.flush()
        results[kind] = batch_id
    return results


def import_all(database_url: str | None = None) -> dict[str, Any]:
    """Import every migrated source (one transaction each) into the store at
    ``database_url`` (default: the settings database)."""

    with session_scope(database_url) as session:
        catalog = import_catalog(session)
        overrides = import_funnel_overrides(session)
        batches = import_quality_inputs(session)
    return {
        "catalog": catalog,
        "funnel_overrides": overrides,
        "quality_batches": batches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-quality", action="store_true", help="skip the big facts import")
    args = parser.parse_args(argv)
    from fdc.config import get_settings

    if args.skip_quality:
        with session_scope() as session:
            print("catalog:", import_catalog(session))
            print("funnel_overrides:", import_funnel_overrides(session))
        return 0
    print(json.dumps(import_all(get_settings().database_url), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
