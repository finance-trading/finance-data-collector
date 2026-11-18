from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute


def client():
    isolated = FastAPI()
    isolated.router.routes.extend(route for route in app.routes if isinstance(route, APIRoute))
    return TestClient(isolated)

from fdc.api import app
from fdc.models import CompanyQualityScore


def score(snapshot_id, cutoff, calculated_at, value, available=True):
    return CompanyQualityScore(
        snapshot_id=snapshot_id, ticker="MSFT", cik="0000789019", company_name="Microsoft",
        sector="Technology", rating_cutoff=cutoff, calculated_at=calculated_at,
        rule_version="CQ_V2", semantic_policy="policy", source_facts_sha256="a" * 64,
        quality_score=value, score_available=available, status="UNKNOWN",
        revenue_growth_dimension=Decimal("10"), dimension_count=4, peer_count=20,
        unknown_reasons=["missing_dimension"], v2_unknown_reasons=["missing_debt"],
        v2_hard_status="UNKNOWN", v2_hard_gate_count=3, v2_hard_gate_total=5,
    )


def test_latest_quality_score_and_diagnostic_value(session):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    session.add_all([
        score("a", date(2024, 1, 1), now, Decimal("10")),
        score("b", date(2025, 1, 1), now, Decimal("25")),
        score("c", date(2025, 1, 1), now, Decimal("42.5"), False),
    ])
    session.commit()
    response = client().get("/api/v1/companies/msft/quality-score")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "MSFT"
    assert body["snapshot_id"] == "c"
    assert float(body["quality_score"]) == 42.5
    assert body["score_available"] is False
    assert body["unknown_reasons"] == ["missing_dimension"]
    assert body["v2_unknown_reasons"] == ["missing_debt"]
    assert body["source_facts_sha256"] == "a" * 64
    assert float(body["revenue_growth_dimension"]) == 10


def test_quality_score_distinguishes_unknown_company_from_missing_score(engine):
    test_client = client()
    unknown = test_client.get("/api/v1/companies/NOTACOMPANY/quality-score")
    missing = test_client.get("/api/v1/companies/MSFT/quality-score")
    assert unknown.status_code == 404
    assert missing.status_code == 404
    assert unknown.json()["detail"] != missing.json()["detail"]
