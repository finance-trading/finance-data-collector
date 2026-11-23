from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from fdc.api import app
from fdc.models import AnalystOpinion


def client():
    isolated = FastAPI()
    isolated.router.routes.extend(route for route in app.routes if isinstance(route, APIRoute))
    return TestClient(isolated)


def row(ticker, firm, days_ago, target, grade, source_row=None):
    now = datetime.now(UTC)
    row = AnalystOpinion(
        ticker=ticker, firm=firm, action_at=now - timedelta(days=days_ago),
        action="main", to_grade=grade, price_target=target,
        price_target_action="Raises", source="yahoo_upgrade_downgrade",
        fetched_at=now,
    )
    return row


def test_analyst_opinions_lists_latest_per_firm_and_consensus(session):
    session.add_all([
        row("AAPL", "Bernstein", 5, 380.0, "Buy"),
        row("AAPL", "JP Morgan", 30, 355.0, "Overweight"),
        row("AAPL", "UBS", 40, 300.0, "Neutral"),
    ])
    session.commit()

    response = client().get("/api/v1/companies/aapl/analyst-opinions")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["firm_count"] == 3
    assert body["mean_target"] == round((380.0 + 355.0 + 300.0) / 3, 2)
    assert body["firms"][0]["firm"] == "Bernstein"  # newest first
    assert {f["firm"] for f in body["firms"]} == {"Bernstein", "JP Morgan", "UBS"}
    assert body["rating_skew"] in ("buy", "hold", "sell")


def test_analyst_opinions_empty_when_no_coverage(session):
    response = client().get("/api/v1/companies/aapl/analyst-opinions")
    assert response.status_code == 200
    body = response.json()
    assert body["firms"] == []
    assert body["mean_target"] is None
    assert body["firm_count"] == 0


def test_analyst_opinions_404_for_unknown_ticker():
    response = client().get("/api/v1/companies/notacat/analyst-opinions")
    assert response.status_code == 404
