"""Tests for the one-shot import of file-based business data into the DB."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdc.data_import import import_catalog, import_funnel_overrides, import_quality_inputs
from fdc.models import (
    AiCompany,
    AiLayer,
    AiSegment,
    FunnelOverride,
    QualityAnnualFact,
    QualityInputBatch,
    QualityPeer,
)
from sqlalchemy import select

CATALOG = {
    "layers": [
        {"id": "infra", "name": "算力基础设施与云", "name_en": "Cloud", "summary": "s",
         "segments": ["云与超大规模"]},
    ],
    "companies": [
        {"ticker": "SPCX", "name": "SpaceX", "sector": "Technology", "industry": "System Software",
         "layer": "infra", "segment": "云与超大规模", "also_in": [], "description": "d"},
        {"ticker": "ANT", "name": "Anthropic", "sector": "Technology", "industry": "Application Svc",
         "layer": "infra", "segment": "云与超大规模", "description": "d"},
    ],
}

OVERRIDES = {"_说明": "doc", "SPCX": {"tier": 1, "note": "T1 核心：云厂商。"}, "ANT": {"tier": 1}}


@pytest.fixture
def session(engine):
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        yield session


def test_import_catalog_creates_rows(session, tmp_path):
    path = tmp_path / "ai_companies.json"
    path.write_text(json.dumps(CATALOG))
    counts = import_catalog(session, path)
    assert counts == {"layers": 1, "segments": 1, "companies": 2}
    assert session.scalars(select(AiCompany)).all()[0].ticker in {"SPCX", "ANT"}
    assert session.scalars(select(AiLayer)).all()[0].position == 0
    assert session.scalars(select(AiSegment)).all()[0].position == 0


def test_import_catalog_is_idempotent(session, tmp_path):
    path = tmp_path / "ai_companies.json"
    path.write_text(json.dumps(CATALOG))
    import_catalog(session, path)
    import_catalog(session, path)
    assert len(session.scalars(select(AiCompany)).all()) == 2


def test_import_catalog_removes_stale_rows(session, tmp_path):
    path = tmp_path / "ai_companies.json"
    path.write_text(json.dumps(CATALOG))
    import_catalog(session, path)
    reduced = {"layers": CATALOG["layers"], "companies": [CATALOG["companies"][0]]}
    path.write_text(json.dumps(reduced))
    counts = import_catalog(session, path)
    assert counts["companies"] == 1
    assert {c.ticker for c in session.scalars(select(AiCompany)).all()} == {"SPCX"}


def test_import_funnel_overrides(session, tmp_path):
    path = tmp_path / "funnel_overrides.json"
    path.write_text(json.dumps(OVERRIDES))
    count = import_funnel_overrides(session, path)
    assert count == 2
    rows = {r.ticker: r for r in session.scalars(select(FunnelOverride)).all()}
    assert rows["SPCX"].tier == 1 and rows["SPCX"].note == "T1 核心：云厂商。"
    assert rows["ANT"].note == ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_quality_inputs(session, tmp_path):
    facts = tmp_path / "facts.csv.gz"
    peers = tmp_path / "peers.csv.gz"
    with gzip.open(facts, "wt", newline="") as handle:
        csv.writer(handle).writerows([
            ["cik", "concept", "label", "value", "numeric_value", "unit", "period_type",
             "period_start", "period_end", "fiscal_year", "fiscal_period", "accession",
             "filing_date", "form_type", "statement_type", "taxonomy", "scale", "data_quality",
             "is_audited", "confidence_score", "period_days", "period_shape", "metric"],
            ["0000001800", "us-gaap:Revenues", "Revenue", "1.0", "1.0", "USD", "duration",
             "2025-01-01", "2025-09-30", "2025", "FY", "acc-1", "2025-11-01", "10-K",
             "income", "us-gaap", "", "high", "True", "0.9", "364", "annual", "revenue"],
        ])
    with gzip.open(peers, "wt", newline="") as handle:
        csv.writer(handle).writerows([
            ["source_symbol", "canonical_symbol", "company_name", "gics_sector",
             "gics_sub_industry", "cik", "date_added"],
            ["AAPL", "AAPL", "Apple", "Technology", "Semiconductors", "0000320193", "2026-09-01"],
        ])
    manifest = {
        "facts_path": str(facts),
        "facts_sha256": _sha256(facts),
        "peer_universe_path": str(peers),
        "peer_universe_sha256": _sha256(peers),
        "rating_cutoff": "2026-09-30",
        "rule_version": "CQ_V2",
        "semantic_policy": "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2",
    }
    manifest_path = tmp_path / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    ids = import_quality_inputs(session, manifest_path)
    assert set(ids) == {"annual_facts", "peer_universe"}
    batch = session.get(QualityInputBatch, ids["annual_facts"])
    assert batch.sha256 == _sha256(facts)
    assert batch.row_count == 1
    fact = session.scalars(select(QualityAnnualFact)).one()
    assert fact.cik == "0000001800" and fact.numeric_value is not None
    peer = session.scalars(select(QualityPeer)).one()
    assert peer.canonical_symbol == "AAPL"


def test_import_quality_inputs_rejects_sha_mismatch(session, tmp_path):
    facts = tmp_path / "facts.csv.gz"
    peers = tmp_path / "peers.csv.gz"
    with gzip.open(facts, "wt", newline="") as handle:
        csv.writer(handle).writerows([
            ["cik", "concept", "label", "value", "numeric_value", "unit", "period_type",
             "period_start", "period_end", "fiscal_year", "fiscal_period", "accession",
             "filing_date", "form_type", "statement_type", "taxonomy", "scale", "data_quality",
             "is_audited", "confidence_score", "period_days", "period_shape", "metric"],
            ["1", "c", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ])
    with gzip.open(peers, "wt", newline="") as handle:
        csv.writer(handle).writerows([
            ["source_symbol", "canonical_symbol", "company_name", "gics_sector",
             "gics_sub_industry", "cik", "date_added"],
            ["AAPL", "AAPL", "Apple", "", "", "0000320193", "2026-09-01"],
        ])
    manifest_path = tmp_path / "source_manifest.json"
    manifest_path.write_text(json.dumps({
        "facts_path": str(facts),
        "facts_sha256": "0" * 64,  # deliberately wrong
        "peer_universe_path": str(peers),
        "peer_universe_sha256": _sha256(peers),
    }))
    with pytest.raises(ValueError, match="sha256"):
        import_quality_inputs(session, manifest_path)
