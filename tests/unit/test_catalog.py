"""Catalog validation, ordering, and database merge behavior."""

from __future__ import annotations

import json

from fdc.catalog import list_companies, list_layers, load_catalog


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
