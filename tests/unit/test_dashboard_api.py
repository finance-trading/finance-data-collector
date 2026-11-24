from fastapi.testclient import TestClient
from datetime import UTC, datetime



def test_overview_market_and_news_routes(monkeypatch):
    from fdc import api, market, news

    monkeypatch.setattr(api.catalog, "read_overview", lambda: {
        "as_of": "2026-11-23", "total_companies": 1,
        "tiers": {"1": 1, "2": 0, "3": 0}, "total_market_cap": 100,
        "avg_quality_score": 80, "gainers": [], "losers": [],
    })
    monkeypatch.setattr(market, "read_market", lambda: {"as_of": None, "indices": []})
    monkeypatch.setattr(news, "read_news", lambda limit, per_source=None: {"as_of": None, "items": [], "sources": []})
    monkeypatch.setattr(news, "collect", lambda: 0)
    client = TestClient(api.app)
    local = TestClient(api.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 51515))

    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["tiers"]["1"] == 1
    assert client.get("/api/v1/market").json() == {"as_of": None, "indices": []}
    assert client.get("/api/v1/news?limit=10").json()["items"] == []
    assert local.post("/api/v1/news/refresh").status_code == 200
    assert client.post("/api/v1/news/refresh").status_code in {401, 403}


def test_news_limit_is_bounded(monkeypatch):
    from fdc import api, news

    monkeypatch.setattr(news, "read_news", lambda limit, per_source=None: {"as_of": None, "items": [], "sources": []})
    client = TestClient(api.app)
    assert client.get("/api/v1/news?limit=0").status_code == 422


def test_news_route_forwards_per_source(monkeypatch):
    from fdc import api, news

    calls = []
    monkeypatch.setattr(news, "read_news", lambda limit, per_source=None:
        calls.append((limit, per_source)) or {"as_of": None, "items": [], "sources": []})
    client = TestClient(api.app)
    client.get("/api/v1/news?limit=20&per_source=5")
    assert calls == [(20, 5)]


def test_market_and_news_endpoints_accept_injected_storage(tmp_path):
    from sqlalchemy.orm import sessionmaker

    from fdc import market, news
    from fdc.db import get_engine
    from fdc.models import MarketQuote, NewsItem, create_all_for_tests

    engine = get_engine(f"sqlite:///{tmp_path / 'api.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session, session.begin():
        session.add(MarketQuote(symbol="^GSPC", label="S&P 500", metrics={
            "close": 6000, "change_pct": 1.2, "spark": [5900, 6000],
        }))
        session.add(NewsItem(source="CNBC", external_id="n1", title="Headline",
            url="https://example.test/n1", published_at=None,
            collected_at=datetime.now(UTC)))

    assert market.read_market(factory)["indices"][0]["spark"] == [5900, 6000]
    assert news.read_news(1, session_factory=factory)["items"][0]["title"] == "Headline"
