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

