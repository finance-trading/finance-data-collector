"""DB-first read paths with file fallback for an unpopulated store.

Migration 0014 moves the catalog, funnel overrides and quality inputs into
the relational store.  Production reads prefer the DB; an empty DB (unit
tests, fresh checkout before the import ran) falls back to the checked-in
files so existing behavior and the test suite keep working.
"""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdc import catalog as fdc_catalog
from fdc import funnel as fdc_funnel
from fdc import quality_facts_external as qfe
from fdc.data_import import import_catalog, import_funnel_overrides, import_quality_inputs
from fdc.models import AiCompany, FunnelOverride

CATALOG = {
    "layers": [
        {"id": "infra", "name": "算力基础设施与云", "name_en": "Cloud", "summary": "s",
         "segments": ["云与超大规模"]},
    ],
    "companies": [
        {"ticker": "SPCX", "name": "SpaceX", "sector": "Technology", "industry": "System Software",
         "layer": "infra", "segment": "云与超大规模", "description": "d"},
        {"ticker": "ANT", "name": "Anthropic", "sector": "Technology", "industry": "Application Svc",
         "layer": "infra", "segment": "云与超大规模", "description": "d"},
    ],
}


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


def _seed_catalog(session, tmp_path) -> Path:
    path = tmp_path / "ai_companies.json"
    path.write_text(json.dumps(CATALOG))
    import_catalog(session, path)
    session.commit()
    return path


def test_load_catalog_prefers_db(session, tmp_path, monkeypatch):
    catalog_path = _seed_catalog(session, tmp_path)
    # The file on disk holds a *different* universe; the DB must win.
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"layers": CATALOG["layers"], "companies": CATALOG["companies"][:1]}))
    monkeypatch.setattr(fdc_catalog, "CATALOG_PATH", other)
    view = fdc_catalog.load_catalog()
    assert [c.ticker for c in view.companies] == ["SPCX", "ANT"]


def test_load_catalog_falls_back_to_file(session, tmp_path, monkeypatch):
    catalog_path = tmp_path / "ai_companies.json"
    catalog_path.write_text(json.dumps(CATALOG))
    monkeypatch.setattr(fdc_catalog, "CATALOG_PATH", catalog_path)
    view = fdc_catalog.load_catalog()
    assert [c.ticker for c in view.companies] == ["SPCX", "ANT"]
    assert len(session.scalars(select(AiCompany)).all()) == 0


def test_load_overrides_prefers_db(session, tmp_path, monkeypatch):
    overrides_path = _seed_overrides(tmp_path)
    import_funnel_overrides(session, overrides_path)
    session.commit()
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"ZZZ": {"tier": 3, "note": "stale"}}))
    monkeypatch.setattr(fdc_funnel, "OVERRIDES_PATH", stale)
    overrides = fdc_funnel.load_overrides()
    assert "SPCX" in overrides and "ZZZ" not in overrides


def _seed_overrides(tmp_path: Path) -> Path:
    path = tmp_path / "funnel_overrides.json"
    path.write_text(json.dumps({"_说明": "doc", "SPCX": {"tier": 1, "note": "T1 核心：云厂商。"}}))
    return path


def test_load_overrides_falls_back_to_file(session, tmp_path, monkeypatch):
    overrides = _seed_overrides(tmp_path)
    monkeypatch.setattr(fdc_funnel, "OVERRIDES_PATH", overrides)
    result = fdc_funnel.load_overrides()
    assert result["SPCX"]["tier"] == 1
    assert not result.get("_说明")


def test_upsert_override_targets_db_when_populated(session, tmp_path, monkeypatch):
    overrides_path = _seed_overrides(tmp_path)
    import_funnel_overrides(session, overrides_path)
    session.commit()
    monkeypatch.setattr(fdc_funnel, "OVERRIDES_PATH", overrides_path)
    fdc_funnel.upsert_override("ANT", 1, "T1 核心：大模型公司。")
    rows = {r.ticker: r.note for r in session.scalars(select(FunnelOverride)).all()}
    assert rows == {"SPCX": "T1 核心：云厂商。", "ANT": "T1 核心：大模型公司。"}


def _seed_quality(tmp_path: Path) -> Path:
    import hashlib
    import shutil

    facts = tmp_path / "facts.csv.gz"
    peers = tmp_path / "peers.csv.gz"
    with gzip.open(facts, "wt", newline="") as handle:
        csv.writer(handle).writerows([
            ["cik", "concept", "label", "value", "numeric_value", "unit", "period_type",
             "period_start", "period_end", "fiscal_year", "fiscal_period", "accession",
             "filing_date", "form_type", "statement_type", "taxonomy", "scale", "data_quality",
             "is_audited", "confidence_score", "period_days", "period_shape", "metric"],
            ["0000001800", "us-gaap:Revenues", "Revenue", "100.0", "100.0", "USD", "duration",
             "2025-01-01", "2025-09-30", "2025", "FY", "acc-1", "2025-11-01", "10-K",
             "income", "us-gaap", "", "high", "True", "0.9", "364", "annual", "revenue"],
        ])
    with gzip.open(peers, "wt", newline="") as handle:
        csv.writer(handle).writerows([
            ["source_symbol", "canonical_symbol", "company_name", "gics_sector",
             "gics_sub_industry", "cik", "date_added"],
            ["AAPL", "AAPL", "Apple", "Technology", "Semiconductors", "0000320193", "2026-09-01"],
        ])

    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    manifest = {
        "facts_path": str(facts), "facts_sha256": sha(facts),
        "peer_universe_path": str(peers), "peer_universe_sha256": sha(peers),
        "rating_cutoff": "2026-09-30", "rule_version": "CQ_V2",
        "semantic_policy": "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2",
    }
    manifest_path = tmp_path / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def test_load_sec_facts_prefers_db(session, tmp_path, monkeypatch):
    manifest = _seed_quality(tmp_path)
    import_quality_inputs(session, manifest)
    session.commit()
    frame = qfe.load_sec_facts()
    assert len(frame) == 1
    assert frame.iloc[0]["cik"] == "0000001800"
    assert frame.iloc[0]["metric"] == "revenue"


def test_load_universe_prefers_db(session, tmp_path, monkeypatch):
    manifest = _seed_quality(tmp_path)
    import_quality_inputs(session, manifest)
    session.commit()
    frame = qfe.load_universe()
    assert len(frame) == 1
    assert frame.iloc[0]["canonical_symbol"] == "AAPL"
