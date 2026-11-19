"""Import precomputed company quality snapshots without storing source facts."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from fdc.data_files import CATALOG_PATH, DATA_ROOT
from fdc.models import CompanyQualityScore, CompanyQualitySnapshot

SNAPSHOT_PATH = DATA_ROOT / "company_quality" / "source_rating_snapshot.csv.gz"
MANIFEST_PATH = DATA_ROOT / "company_quality" / "source_manifest.json"

DIMENSIONS = (
    "revenue_growth_dimension", "operating_margin_dimension", "cash_conversion_dimension",
    "capital_efficiency_dimension", "financial_strength_dimension",
)
DECIMAL_FIELDS = (
    "quality_score", *DIMENSIONS, "v2_net_debt_ebitda", "v2_interest_coverage",
    "v2_cumulative_net_income", "v2_cumulative_cfo",
)
INT_FIELDS = (
    "dimension_count", "peer_count", "v2_hard_gate_count", "v2_hard_gate_total",
    "v2_positive_operating_income_years", "v2_positive_cfo_years",
)
LIST_FIELDS = ("period_ends", "unknown_reasons", "v2_unknown_reasons")
REQUIRED_FIELDS = {
    "canonical_symbol", "cik", "company_name", "gics_sector", "rating_cutoff", "rule_version",
    "semantic_policy", "score_available", "status", "v2_hard_status", *DECIMAL_FIELDS,
    *INT_FIELDS, *LIST_FIELDS,
}


def _decimal(value: str) -> Decimal | None:
    text = value.strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid numeric score value: {value!r}") from error
    # A non-finite value (inf / -inf / nan) is not a usable number; the source
    # snapshot emits these for, e.g., interest coverage with near-zero
    # interest expense. Treat as unavailable rather than certifying it.
    if not number.is_finite():
        return None
    return number


def _int(value: str) -> int | None:
    """Parse an integer field that may carry a trailing ``.0`` from CSV export."""
    if not value.strip():
        return None
    text = value.strip()
    if text.endswith(".0"):
        text = text[:-2]
    try:
        return int(text)
    except ValueError:
        try:
            number = float(text)
        except ValueError as error:
            raise ValueError(f"invalid integer score value: {value!r}") from error
        if not number.is_integer():
            raise ValueError(f"non-integer score value: {value!r}")
        return int(number)


def seed_from_source_snapshot(
    session: Session, snapshot_id: str, rating_cutoff: date, calculated_at: datetime,
) -> int:
    """Insert catalog scores atomically, refusing a run that already exists.

    The caller owns the transaction: a flush failure must be followed by rollback.
    """
    if not snapshot_id.strip():
        raise ValueError("snapshot_id must not be empty")
    manifest = json.loads(MANIFEST_PATH.read_text())
    actual = hashlib.sha256(SNAPSHOT_PATH.read_bytes()).hexdigest()
    if actual != manifest["source_rating_snapshot_sha256"]:
        raise ValueError(f"SHA-256 mismatch for source snapshot: {actual}")
    if session.get(CompanyQualitySnapshot, snapshot_id) is not None:
        raise ValueError(f"snapshot already exists: {snapshot_id}")
    companies = json.loads(CATALOG_PATH.read_text())["companies"]
    tickers: dict[str, dict] = {}
    for company in companies:
        ticker = str(company["ticker"]).strip().upper()
        if not ticker:
            raise ValueError("catalog company has empty ticker")
        if ticker in tickers:
            raise ValueError(f"duplicate catalog ticker: {ticker}")
        tickers[ticker] = company
    with gzip.open(SNAPSHOT_PATH, "rt", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing source columns: {', '.join(sorted(missing))}")
        rows = []
        for row in reader:
            ticker = row["canonical_symbol"].strip().upper()
            if any(row[key] != manifest[key] for key in ("rating_cutoff", "rule_version", "semantic_policy")):
                raise ValueError(f"source metadata mismatch for {ticker}")
            if ticker in tickers:
                rows.append(row)
    if not rows:
        raise ValueError("no matching catalog companies in snapshot")
    pending = []
    seen = set()
    for row in rows:
        ticker = row["canonical_symbol"].strip().upper()
        if ticker in seen:
            raise ValueError(f"duplicate source ticker: {ticker}")
        seen.add(ticker)
        if date.fromisoformat(row["rating_cutoff"]) != rating_cutoff:
            raise ValueError(f"source cutoff mismatch for {ticker}")
        catalog_value = str(tickers[ticker].get("cik") or "").strip()
        source_value = str(row["cik"]).strip()
        for value in (catalog_value, source_value):
            if value and (not value.isascii() or not value.isdigit() or len(value) > 10):
                raise ValueError(f"invalid CIK for {ticker}: {value}")
        catalog_cik = catalog_value.zfill(10) if catalog_value else ""
        source_cik = source_value.zfill(10) if source_value else ""
        if catalog_cik and not source_cik:
            raise ValueError(f"missing source CIK for {ticker}")
        if catalog_cik and source_cik and catalog_cik != source_cik:
            raise ValueError(f"CIK mismatch for {ticker}: catalog={catalog_cik} source={source_cik}")
        available = row["score_available"].strip().lower()
        if available not in {"true", "false"}:
            raise ValueError(f"invalid score availability for {ticker}")
        fields = {key: _decimal(row[key]) for key in DECIMAL_FIELDS}
        fields.update({key: _int(row[key]) for key in INT_FIELDS})
        fields.update({key: [part for part in row[key].split("|") if part] for key in LIST_FIELDS})
        pending.append(CompanyQualityScore(
            snapshot_id=snapshot_id, ticker=ticker, cik=source_cik or None,
            company_name=row["company_name"], sector=row["gics_sector"] or None,
            rating_cutoff=rating_cutoff, calculated_at=calculated_at,
            rule_version=row["rule_version"], semantic_policy=row["semantic_policy"],
            source_facts_sha256=manifest["facts_sha256"], score_available=available == "true",
            status=row["status"], v2_hard_status=row["v2_hard_status"], **fields,
        ))
    # Reserve the run ID first. The primary key serializes concurrent writers,
    # even when their company sets do not overlap. Both writes share the
    # caller's transaction, so a later failure rolls the reservation back too.
    session.add(CompanyQualitySnapshot(snapshot_id=snapshot_id, calculated_at=calculated_at))
    session.flush()
    session.add_all(pending)
    session.flush()
    return len(pending)
