"""Catalog validation, ordering, and database merge behavior."""

from __future__ import annotations

import json

import fdc.catalog
from fdc.catalog import list_companies, list_layers, load_catalog, read_quotes


def _catalog_path(tmp_path):
    path = tmp_path / "ai_companies.json"
    path.write_text(
        json.dumps(
            {
                "layers": [
                    {
                        "id": "power",
                        "name": "Power",
                        "name_en": "Power",
                        "summary": "Power infrastructure",
                        "segments": ["Grid"],
                    },
                    {
                        "id": "silicon",
                        "name": "Silicon",
                        "name_en": "Silicon",
                        "summary": "Compute hardware",
                        "segments": ["Compute"],
                    },
                ],
                "companies": [
                    {
                        "ticker": "VRT",
                        "name": "Vertiv",
                        "sector": "Industrials",
                        "industry": "Electrical Equipment",
                        "layer": "power",
                        "segment": "Grid",
                        "description": "Power infrastructure",
                    },
                    {
                        "ticker": "NVDA",
                        "name": "NVIDIA",
                        "sector": "Technology",
                        "industry": "Semiconductors",
                        "layer": "silicon",
                        "segment": "Compute",
                        "description": "Accelerated compute",
                    },
                    {
                        "ticker": "AMD",
                        "name": "AMD",
                        "sector": "Technology",
                        "industry": "Semiconductors",
                        "layer": "silicon",
                        "segment": "Compute",
                        "description": "Compute silicon",
                    },
                ],
            }
        )
    )
    return path


def test_catalog_preserves_declared_layer_and_company_order(tmp_path):
    catalog = load_catalog(_catalog_path(tmp_path))

    assert [layer.id for layer in catalog.layers] == ["power", "silicon"]
    assert [company.ticker for company in catalog.companies] == ["VRT", "NVDA", "AMD"]


def test_layer_facets_include_declared_segment_counts(tmp_path):
    result = list_layers(_catalog_path(tmp_path))

    assert result.total_companies == 3
    assert result.layers[1].count == 2
    assert [(segment.name, segment.count) for segment in result.layers[1].segments] == [
        ("Compute", 2),
    ]


def test_directory_includes_catalog_only_company(
    tmp_path, engine, session_factory
):
    result = list_companies(
        query="vertiv",
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )

    assert result.total == 1
    assert result.companies[0].ticker == "VRT"
    assert result.companies[0].ingestion_status == "not_ingested"
    assert result.companies[0].filing_count == 0
    assert result.companies[0].research_available is False


def test_directory_filters_before_paginating(tmp_path, engine, session_factory):
    result = list_companies(
        query=None,
        layer="silicon",
        segment="Compute",
        ingestion_status="not_ingested",
        limit=1,
        offset=1,
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )

    assert result.total == 2
    assert [company.ticker for company in result.companies] == ["AMD"]


def test_directory_filters_multiple_layers_before_paginating(tmp_path, engine, session_factory):
    result = list_companies(
        query=None,
        layer=["power", "silicon"],
        segment=None,
        ingestion_status=None,
        limit=2,
        offset=1,
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )

    assert result.total == 3
    assert [company.ticker for company in result.companies] == ["NVDA", "AMD"]


def test_directory_merges_cached_quotes(tmp_path, engine, session_factory, monkeypatch):
    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    "VRT": {
                        "price": 252.18,
                        "previous_close": 246.12,
                        "change_pct": 2.46,
                        "week_change_pct": -1.87,
                        "change_52w_pct": 34.5,
                        "market_cap": 97086314647,
                    },
                    "NVDA": {
                        "price": 233.95,
                        "previous_close": 230.86,
                        "change_pct": 1.34,
                        "week_change_pct": 5.61,
                        "change_52w_pct": -18.07,
                        "market_cap": 5649190576309,
                    },
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)

    result = list_companies(
        query=None,
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )

    by_ticker = {company.ticker: company for company in result.companies}
    assert by_ticker["VRT"].price == 252.18
    assert by_ticker["VRT"].market_cap == 97086314647
    assert by_ticker["VRT"].change_pct == 2.46
    assert by_ticker["VRT"].week_change_pct == -1.87
    assert by_ticker["VRT"].change_52w_pct == 34.5
    assert by_ticker["VRT"].quote_as_of.isoformat() == "2026-10-04"
    # AMD is in the fixture catalog but has no entry in quotes.json — nulls
    # are expected for it, not for VRT/NVDA which both have quotes.
    assert by_ticker["NVDA"].price == 233.95
    assert by_ticker["NVDA"].market_cap == 5649190576309
    assert by_ticker["NVDA"].change_pct == 1.34
    assert by_ticker["NVDA"].week_change_pct == 5.61
    assert by_ticker["NVDA"].change_52w_pct == -18.07
    assert by_ticker["AMD"].price is None
    assert by_ticker["AMD"].week_change_pct is None


def test_directory_joins_funnel_tier_and_filters(
    tmp_path, engine, session_factory, monkeypatch
):
    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    "VRT": {"market_cap": 100},
                    "NVDA": {"market_cap": 300},
                    "AMD": {"market_cap": 200},
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)
    # Deterministic: ignore whatever is in the tracked overrides file.
    monkeypatch.setattr(fdc.catalog, "load_overrides", lambda: {})

    result = list_companies(
        None, None, None, None, 25, 0,
        catalog_path=_catalog_path(tmp_path), session_factory=session_factory,
    )
    by_ticker = {company.ticker: company for company in result.companies}
    # Power has one member (T1); silicon ranks NVDA(300) > AMD(200) -> T1/T2.
    assert by_ticker["VRT"].funnel_tier == 1
    assert by_ticker["NVDA"].funnel_tier == 1
    assert by_ticker["AMD"].funnel_tier == 2
    assert by_ticker["AMD"].funnel_tier_name == "重要"
    assert by_ticker["AMD"].funnel_tier_source == "自动"

    filtered = list_companies(
        None, None, None, None, 25, 0, funnel_tier=2,
        catalog_path=_catalog_path(tmp_path), session_factory=session_factory,
    )
    assert [company.ticker for company in filtered.companies] == ["AMD"]


def test_funnel_tier_index_resolves_tiers(tmp_path, monkeypatch):
    """The endpoint helper resolves tiers off catalog + quotes + overrides."""
    catalog_path = _catalog_path(tmp_path)
    monkeypatch.setattr(fdc.catalog, "CATALOG_PATH", catalog_path)
    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    "VRT": {"market_cap": 100},
                    "NVDA": {"market_cap": 300},
                    "AMD": {"market_cap": 200},
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)
    monkeypatch.setattr(fdc.catalog, "load_overrides", lambda: {})

    tiers = fdc.catalog.funnel_tier_index()
    # Power has one member (T1); silicon ranks NVDA(300) > AMD(200) -> T1/T2.
    assert tiers["VRT"]["tier"] == 1
    assert tiers["NVDA"]["tier"] == 1
    assert tiers["AMD"]["tier"] == 2
    assert tiers["AMD"]["source"] == "自动"


def test_directory_exposes_saved_ranges_and_editable_watch_items(
    tmp_path, engine, session_factory, monkeypatch
):
    from fdc.models import ResearchAnnotation

    monkeypatch.setattr(fdc.catalog, "load_overrides", lambda: {})
    with session_factory() as session:
        session.add(ResearchAnnotation(
            ticker="NVDA", observe_low=180, observe_high=200,
            entry_low=150, entry_high=160,
            watch_items=[
                {"text": "Track revenue", "priority": 2},
                {"text": "Review margins", "priority": 1},
            ],
        ))
        session.commit()

    result = list_companies(
        None, None, None, None, 25, 0,
        catalog_path=_catalog_path(tmp_path), session_factory=session_factory,
    )
    by_ticker = {company.ticker: company for company in result.companies}
    nvda = by_ticker["NVDA"]
    assert nvda.observation_range.low == 180
    assert nvda.observation_range.high == 200
    assert nvda.entry_range.low == 150
    assert nvda.add_range.low is None
    assert nvda.annotation_saved is True
    assert [item.priority for item in nvda.watch_items] == [1, 2]
    assert [item.text for item in nvda.watch_items] == ["Review margins", "Track revenue"]

    amd = by_ticker["AMD"]
    assert amd.observation_range.low is None
    assert amd.entry_range.high is None
    assert amd.annotation_saved is False
    assert [item.priority for item in amd.watch_items] == [1, 2, 3]


def test_directory_sorts_globally_not_per_page(
    tmp_path, engine, session_factory, monkeypatch
):
    """Sorting must order all companies, then paginate — not reorder one page."""

    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    # AMD sorts last by market cap but is first by daily change.
                    "AMD": {"market_cap": 295_000_000_000, "change_pct": 8.1},
                    "VRT": {
                        "market_cap": 97_086_314_647,
                        "change_pct": 2.46,
                    },
                    "NVDA": {
                        "market_cap": 5_649_190_576_309,
                        "change_pct": 1.34,
                    },
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)

    descending = list_companies(
        query=None,
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        sort_by="market_cap",
        order="desc",
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )
    # Descending: NVDA > AMD > VRT.
    assert [c.ticker for c in descending.companies] == ["NVDA", "AMD", "VRT"]
    assert descending.sort_by == "market_cap"
    assert descending.order == "desc"

    ascending = list_companies(
        query=None,
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        sort_by="market_cap",
        order="asc",
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )
    assert [c.ticker for c in ascending.companies] == ["VRT", "AMD", "NVDA"]

    # Pagination walks the same globally ordered list.
    second_page = list_companies(
        query=None,
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=1,
        offset=1,
        sort_by="market_cap",
        order="desc",
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )
    assert [c.ticker for c in second_page.companies] == ["AMD"]


def test_directory_sorts_by_daily_change_and_keeps_missing_last(
    tmp_path, engine, session_factory, monkeypatch
):
    """Companies with no quote must sink to the bottom in either direction."""

    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    # VRT up, NVDA down; AMD has no quote at all.
                    "VRT": {"change_pct": 2.46},
                    "NVDA": {"change_pct": -1.34},
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)

    def tickers(order):
        return [
            c.ticker
            for c in list_companies(
                query=None,
                layer=None,
                segment=None,
                ingestion_status=None,
                limit=25,
                offset=0,
                sort_by="change_pct",
                order=order,
                catalog_path=_catalog_path(tmp_path),
                session_factory=session_factory,
            ).companies
        ]

    assert tickers("desc") == ["VRT", "NVDA", "AMD"]
    # Ascending puts NVDA first, but AMD stays last, not first.
    assert tickers("asc") == ["NVDA", "VRT", "AMD"]


def test_directory_sorts_by_trailing_returns_and_keeps_missing_last(
    tmp_path, engine, session_factory, monkeypatch
):
    """Each trailing-return key sorts independently, not on change_pct."""

    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    # dd and rise disagree on the winner; AMD has none.
                    "VRT": {
                        "change_pct": 2.46,
                        "week_change_pct": -1.87,
                        "week_rise_pct": 1.2,
                        "change_52w_pct": 34.5,
                        "rise_52w_pct": 41.0,
                    },
                    "NVDA": {
                        "change_pct": -1.34,
                        "week_change_pct": 5.61,
                        "week_rise_pct": 8.9,
                        "change_52w_pct": -18.07,
                        "rise_52w_pct": -12.0,
                    },
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)

    def tickers(sort_by, order):
        return [
            c.ticker
            for c in list_companies(
                query=None,
                layer=None,
                segment=None,
                ingestion_status=None,
                limit=25,
                offset=0,
                sort_by=sort_by,
                order=order,
                catalog_path=_catalog_path(tmp_path),
                session_factory=session_factory,
            ).companies
        ]

    assert tickers("week_change_pct", "desc") == ["NVDA", "VRT", "AMD"]
    assert tickers("week_change_pct", "asc") == ["VRT", "NVDA", "AMD"]
    assert tickers("week_rise_pct", "desc") == ["NVDA", "VRT", "AMD"]
    assert tickers("week_rise_pct", "asc") == ["VRT", "NVDA", "AMD"]
    assert tickers("change_52w_pct", "desc") == ["VRT", "NVDA", "AMD"]
    assert tickers("change_52w_pct", "asc") == ["NVDA", "VRT", "AMD"]
    assert tickers("rise_52w_pct", "desc") == ["VRT", "NVDA", "AMD"]
    assert tickers("rise_52w_pct", "asc") == ["NVDA", "VRT", "AMD"]


def test_directory_tolerates_quotes_without_market_cap(
    tmp_path, engine, session_factory, monkeypatch
):
    """A cache written before market cap landed must still merge cleanly."""

    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {"VRT": {"price": 252.18, "change_pct": 2.46}},
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)

    result = list_companies(
        query=None,
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )

    by_ticker = {company.ticker: company for company in result.companies}
    assert by_ticker["VRT"].price == 252.18
    assert by_ticker["VRT"].market_cap is None
    # A cache written before the trailing returns landed degrades to null too.
    assert by_ticker["VRT"].week_change_pct is None
    assert by_ticker["VRT"].change_52w_pct is None
    assert by_ticker["AMD"].price is None
    assert by_ticker["AMD"].market_cap is None


def test_directory_degrades_when_quotes_file_is_missing(
    tmp_path, engine, session_factory, monkeypatch
):
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", tmp_path / "does_not_exist.json")

    result = list_companies(
        query=None,
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        catalog_path=_catalog_path(tmp_path),
        session_factory=session_factory,
    )

    assert result.total == 3
    for company in result.companies:
        assert company.price is None
        assert company.change_pct is None
        assert company.quote_as_of is None


def test_read_quotes_returns_cached_quotes_with_date(tmp_path, monkeypatch):
    quotes = tmp_path / "quotes.json"
    quotes.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-04T15:00:00+00:00",
                "quotes": {
                    "NVDA": {
                        "price": 233.95,
                        "change_pct": 1.34,
                        "market_cap": 5_649_190_576_309,
                    },
                },
            }
        )
    )
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", quotes)

    view = read_quotes()

    assert view.generated_at == "2026-10-04T15:00:00+00:00"
    assert view.quotes["NVDA"]["change_pct"] == 1.34


def test_read_quotes_degrades_when_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", tmp_path / "does_not_exist.json")

    view = read_quotes()

    assert view.generated_at is None
    assert view.quotes == {}


def test_research_annotation_api_persists_and_validates(
    tmp_path, engine, session_factory, monkeypatch
):
    from fastapi.testclient import TestClient

    from fdc.api import app
    from fdc.models import ResearchAnnotation

    monkeypatch.setattr(fdc.catalog, "CATALOG_PATH", _catalog_path(tmp_path))
    monkeypatch.setattr("fdc.api.SessionLocal", session_factory)
    endpoint = "/api/v1/research/annotations/NVDA"
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 51515))
    payload = {
        "observation_range": {"low": 180, "high": 200},
        "entry_range": {"low": None, "high": None},
        "add_range": {"low": 130, "high": 150},
        "reduce_range": {"low": 250, "high": 270},
        "watch_items": [{"priority": 2, "text": "  Track revenue  "}],
    }
    assert TestClient(app).post(endpoint, json=payload).status_code == 403
    assert client.post(
        endpoint, headers={"Origin": "http://evil.test"}, json=payload
    ).status_code == 403
    assert client.post(endpoint.replace("NVDA", "BAD"), json=payload).status_code == 404
    assert client.post(
        endpoint, json={**payload, "entry_range": {"low": 100, "high": None}}
    ).status_code == 422
    assert client.post(
        endpoint, json={**payload, "add_range": {"low": 160, "high": 150}}
    ).status_code == 422
    assert client.post(
        endpoint, json={**payload, "watch_items": [{"priority": 1, "text": " "}]}
    ).status_code == 422
    assert client.post(
        endpoint, json={**payload, "observation_range": {"low": -1, "high": 200}}
    ).status_code == 422
    assert client.post(endpoint, json={}).status_code == 422
    assert client.post(endpoint, json={"watch_items": None}).status_code == 422

    first = client.post(
        endpoint.replace("NVDA", "AMD"),
        json={"observation_range": {"low": 90, "high": 95}},
    )
    assert first.status_code == 200
    with session_factory() as session:
        seeded = session.get(ResearchAnnotation, "AMD")
        assert seeded.observe_low == 90
        assert [item["priority"] for item in seeded.watch_items] == [1, 2, 3]

    saved = client.post(endpoint, json=payload)
    assert saved.status_code == 200
    assert saved.json()["watch_items"] == [{"priority": 2, "text": "Track revenue"}]
    with session_factory() as session:
        row = session.get(ResearchAnnotation, "NVDA")
        assert row.observe_low == 180
        assert row.add_high == 150
        assert row.watch_items == [{"priority": 2, "text": "Track revenue"}]

    partial = client.post(endpoint, json={"entry_range": {"low": 100, "high": 110}})
    assert partial.status_code == 200
    with session_factory() as session:
        row = session.get(ResearchAnnotation, "NVDA")
        assert row.observe_low == 180
        assert row.entry_low == 100
        assert row.watch_items == [{"priority": 2, "text": "Track revenue"}]

    cleared = client.post(
        endpoint,
        json={
            **payload,
            "watch_items": [],
            "observation_range": {"low": None, "high": None},
        },
    )
    assert cleared.status_code == 200
    with session_factory() as session:
        row = session.get(ResearchAnnotation, "NVDA")
        assert row.observe_low is None
        assert row.watch_items == []


def test_funnel_override_api_persists_and_resets(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fdc import funnel
    from fdc.api import app

    original_upsert = funnel.upsert_override
    original_remove = funnel.remove_override
    original_load = funnel.load_overrides
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"_说明": "keep"}))
    monkeypatch.setattr(fdc.catalog, "CATALOG_PATH", _catalog_path(tmp_path))
    monkeypatch.setattr(fdc.catalog, "QUOTES_PATH", tmp_path / "missing-quotes.json")
    monkeypatch.setattr(
        funnel, "upsert_override",
        lambda ticker, tier, note: original_upsert(ticker, tier, note, path),
    )
    monkeypatch.setattr(funnel, "remove_override", lambda ticker: original_remove(ticker, path))
    monkeypatch.setattr(funnel, "load_overrides", lambda: original_load(path))
    monkeypatch.setattr(fdc.catalog, "load_overrides", lambda: original_load(path))
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 51515))
    endpoint = "/api/v1/funnel/overrides"

    assert client.post(endpoint, json={"ticker": "VRT", "tier": 2}).status_code == 400
    assert client.post(
        endpoint, json={"ticker": "BAD", "tier": 2, "note": "reason"}
    ).status_code == 404
    assert json.loads(path.read_text()) == {"_说明": "keep"}
    assert TestClient(app).post(
        endpoint, json={"ticker": "VRT", "tier": 2, "note": "reason"}
    ).status_code == 403
    assert TestClient(app, base_url="http://remote.test", client=("127.0.0.1", 51515)).post(
        endpoint, json={"ticker": "VRT", "tier": 2, "note": "reason"}
    ).status_code == 403
    assert client.post(
        endpoint, headers={"Origin": "http://another-site.test"},
        json={"ticker": "VRT", "tier": 2, "note": "reason"},
    ).status_code == 403
    assert json.loads(path.read_text()) == {"_说明": "keep"}

    saved = client.post(endpoint, json={"ticker": "vrt", "tier": 2, "note": "priority"})
    assert saved.status_code == 200
    assert saved.json()["tier"] == 2
    assert saved.json()["source"] == "人工"
    assert client.get("/api/v1/funnel/tiers").json()["VRT"]["tier"] == 2
    assert json.loads(path.read_text())["VRT"] == {"tier": 2, "note": "priority"}

    reset = client.post(endpoint, json={"ticker": "VRT", "tier": None})
    assert reset.status_code == 200
    assert reset.json()["tier"] == 1
    assert reset.json()["source"] == "自动"
    assert json.loads(path.read_text()) == {"_说明": "keep"}

