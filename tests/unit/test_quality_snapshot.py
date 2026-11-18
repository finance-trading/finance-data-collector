import csv
import gzip
import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from fdc.models import Base, CompanyQualityScore, CompanyQualitySnapshot
from fdc.quality_snapshot import seed_from_source_snapshot


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    import fdc.quality_snapshot as module

    row = {
        "canonical_symbol": "ABC", "cik": "123", "company_name": "ABC Corp",
        "gics_sector": "Technology", "rating_cutoff": "2026-09-30",
        "rule_version": "CQ_V2", "semantic_policy": "policy", "quality_score": "72.123456",
        "score_available": "True", "status": "QUALIFIED", "dimension_count": "5",
        "peer_count": "12", "period_ends": "2024-12-31|2025-12-31",
        "unknown_reasons": "missing_a|missing_b", "v2_hard_status": "QUALIFIED",
        "v2_unknown_reasons": "", "v2_hard_gate_count": "5", "v2_hard_gate_total": "5",
        "v2_net_debt_ebitda": "1.25", "v2_interest_coverage": "8",
        "v2_cumulative_net_income": "120", "v2_cumulative_cfo": "130",
        "v2_positive_operating_income_years": "5", "v2_positive_cfo_years": "5",
        **{f"{name}_dimension": "70" for name in (
            "revenue_growth", "operating_margin", "cash_conversion", "capital_efficiency", "financial_strength")},
    }
    path = tmp_path / "scores.csv.gz"
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=row.keys())
        writer.writeheader()
        writer.writerows([row, {**row, "canonical_symbol": "XYZ"}])
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"companies": [{"ticker": "ABC", "cik": "0000000123"}]}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"facts_sha256": "a" * 64,
        "source_rating_snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rating_cutoff": "2026-09-30", "rule_version": "CQ_V2", "semantic_policy": "policy"}))
    monkeypatch.setattr(module, "SNAPSHOT_PATH", path)
    monkeypatch.setattr(module, "CATALOG_PATH", catalog)
    monkeypatch.setattr(module, "MANIFEST_PATH", manifest)
    return path, catalog, manifest


def test_seed_filters_catalog_and_preserves_results(inputs):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        args = (session, "run-1", date(2026, 9, 30), datetime(2026, 10, 5, tzinfo=UTC))
        assert seed_from_source_snapshot(*args) == 1
        with pytest.raises(ValueError, match="already exists"):
            seed_from_source_snapshot(*args)
        rows = session.scalars(select(CompanyQualityScore)).all()
        assert len(rows) == 1
        assert rows[0].ticker == "ABC" and rows[0].cik == "0000000123"
        assert rows[0].quality_score == Decimal("72.123456")
        assert rows[0].period_ends == ["2024-12-31", "2025-12-31"]
        assert rows[0].unknown_reasons == ["missing_a", "missing_b"]
        assert rows[0].source_facts_sha256 == "a" * 64


def test_seed_rejects_zero_matches(inputs):
    _, catalog, _ = inputs
    catalog.write_text(json.dumps({"companies": [{"ticker": "NONE"}]}))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, pytest.raises(ValueError, match="match"):
        seed_from_source_snapshot(session, "run-1", date(2026, 9, 30), datetime.now(UTC))


def test_seed_rejects_missing_columns(inputs):
    path, _, manifest = inputs
    with gzip.open(path, "wt") as handle:
        handle.write("canonical_symbol\nABC\n")
    data = json.loads(manifest.read_text())
    data["source_rating_snapshot_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, pytest.raises(ValueError, match="missing"):
        seed_from_source_snapshot(session, "run-1", date(2026, 9, 30), datetime.now(UTC))


def test_seed_rejects_checksum_mismatch(inputs):
    path, _, _ = inputs
    path.write_bytes(path.read_bytes() + b"corrupt")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session, pytest.raises(ValueError, match="SHA-256"):
        seed_from_source_snapshot(session, "run-1", date(2026, 9, 30), datetime.now(UTC))


def test_seed_rejects_identity_conflict_and_duplicate_catalog(inputs):
    _, catalog, _ = inputs
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        catalog.write_text(json.dumps({"companies": [{"ticker": "ABC", "cik": "999"}]}))
        with pytest.raises(ValueError, match="CIK"):
            seed_from_source_snapshot(session, "run-1", date(2026, 9, 30), datetime.now(UTC))
        catalog.write_text(json.dumps({"companies": [{"ticker": "ABC"}, {"ticker": "abc"}]}))
        with pytest.raises(ValueError, match="duplicate"):
            seed_from_source_snapshot(session, "run-1", date(2026, 9, 30), datetime.now(UTC))


def test_snapshot_reservation_rolls_back_with_score_rows(inputs):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_from_source_snapshot(session, "run-rollback", date(2026, 9, 30), datetime.now(UTC))
        assert session.get(CompanyQualitySnapshot, "run-rollback") is not None
        session.rollback()
    with Session(engine) as session:
        assert session.get(CompanyQualitySnapshot, "run-rollback") is None
        assert session.scalars(select(CompanyQualityScore)).all() == []


def test_existing_reservation_rejects_disjoint_company_set(inputs):
    _, catalog, _ = inputs
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_from_source_snapshot(session, "run-shared", date(2026, 9, 30), datetime.now(UTC))
        session.commit()
        catalog.write_text(json.dumps({"companies": [{"ticker": "XYZ"}]}))
        with pytest.raises(ValueError, match="already exists"):
            seed_from_source_snapshot(session, "run-shared", date(2026, 9, 30), datetime.now(UTC))
        assert [row.ticker for row in session.scalars(select(CompanyQualityScore))] == ["ABC"]


def test_real_snapshot_checksum_matches_manifest():
    root = Path(__file__).resolve().parents[2] / "data" / "company_quality"
    manifest = json.loads((root / "source_manifest.json").read_text())
    assert hashlib.sha256((root / "source_rating_snapshot.csv.gz").read_bytes()).hexdigest() == manifest["source_rating_snapshot_sha256"]
