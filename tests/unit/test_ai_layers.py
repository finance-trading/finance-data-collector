"""Unit tests for the AI value-chain layering.

Everything here runs offline: the real universe is validated from the checked-in
JSON, and CIK resolution is stubbed with a fake ticker map.
"""

from __future__ import annotations

import json

import pytest

from fdc import ai_layers
from fdc.ai_layers import (
    UniverseError,
    build_tree,
    enrich_graph,
    render_mermaid,
    render_tree,
    validate_universe,
)

LAYERS = [
    {
        "id": "up",
        "name": "上游",
        "name_en": "Upstream",
        "summary": "s",
        "segments": ["设备", "材料"],
    },
    {"id": "down", "name": "下游", "name_en": "Downstream", "summary": "s", "segments": ["应用"]},
]


def make_company(ticker, layer, segment, cik=1, **extra):
    """Minimal valid company row, with cik already attached."""
    row = {
        "ticker": ticker,
        "name": f"{ticker} Inc",
        "sector": "Technology",
        "industry": "Semiconductors",
        "layer": layer,
        "segment": segment,
        "description": f"{ticker} 描述。",
        "cik": cik,
    }
    row.update(extra)
    return row


def test_real_universe_satisfies_layer_contract():
    companies, layers = ai_layers.load_universe()

    assert [layer["id"] for layer in layers] == [
        "power",
        "silicon",
        "infra",
        "model",
        "app",
        "edge",
    ]
    assert len(companies) >= 90
    assert len({company["ticker"] for company in companies}) == len(companies)
    for layer in layers:
        assert any(company["layer"] == layer["id"] for company in companies), layer["id"]


def test_real_universe_tree_is_ordered_and_complete():
    companies, layers = ai_layers.load_universe()
    fake_map = {company["ticker"].upper(): index + 1 for index, company in enumerate(companies)}
    resolved = ai_layers.resolve_ciks(companies, fake_map)

    tree = build_tree(resolved, layers, "2026-01-01 00:00")
    root = tree["root"]

    assert [layer["name"] for layer in root["children"]] == [layer["name"] for layer in layers]
    leaves = [
        node
        for layer in root["children"]
        for segment in layer["children"]
        for node in segment["children"]
    ]
    assert len(leaves) == len(companies)
    assert tree["stats"]["companies"] == len(companies)
    assert tree["stats"]["segments"] == 25
    assert tree["stats"]["cross_layer"] >= 1
    assert all(node["edgar"].startswith("https://www.sec.gov/") for node in leaves)
    assert all(node["cik"] for node in leaves)


def test_resolve_ciks_skips_unknown_tickers(capsys):
    companies = [make_company("AAA", "up", "设备", cik=1), make_company("ZZZ", "up", "设备", cik=2)]

    resolved = ai_layers.resolve_ciks(companies, {"AAA": 1234})

    assert [company["ticker"] for company in resolved] == ["AAA"]
    assert resolved[0]["cik"] == 1234
    assert "skipping ZZZ" in capsys.readouterr().out


def test_validate_rejects_unknown_layer():
    companies = [make_company("AAA", "nowhere", "设备")]

    with pytest.raises(UniverseError, match="unknown layer"):
        validate_universe(companies, LAYERS)


def test_validate_rejects_undeclared_segment():
    companies = [make_company("AAA", "up", "线路板"), make_company("BBB", "down", "应用")]

    with pytest.raises(UniverseError, match="not declared by layer"):
        validate_universe(companies, LAYERS)


def test_validate_rejects_duplicate_ticker():
    companies = [
        make_company("AAA", "up", "设备"),
        make_company("aaa", "up", "材料"),
        make_company("BBB", "down", "应用"),
    ]

    with pytest.raises(UniverseError, match="duplicate ticker"):
        validate_universe(companies, LAYERS)


def test_validate_rejects_also_in_primary_layer():
    companies = [make_company("AAA", "up", "设备", also_in=["up"])]

    with pytest.raises(UniverseError, match="also_in repeats"):
        validate_universe(companies, LAYERS)


def test_validate_rejects_empty_declared_segment():
    companies = [make_company("AAA", "up", "设备"), make_company("BBB", "down", "应用")]

    with pytest.raises(UniverseError, match="empty segments"):
        validate_universe(companies, LAYERS)


def test_build_tree_orders_layers_and_segments_from_spec():
    companies = [
        make_company("CCC", "down", "应用"),
        make_company("AAA", "up", "材料"),
        make_company("BBB", "up", "设备"),
    ]

    tree = build_tree(companies, LAYERS, "now")
    root = tree["root"]

    assert [layer["name"] for layer in root["children"]] == ["上游", "下游"]
    upstream = root["children"][0]
    assert [segment["name"] for segment in upstream["children"]] == ["设备", "材料"]
    assert [node["ticker"] for node in upstream["children"][0]["children"]] == ["BBB"]
    assert upstream["count"] == 2
    assert tree["stats"] == {"companies": 3, "layers": 2, "segments": 3, "cross_layer": 0}


def test_build_tree_marks_cross_layer_roles():
    companies = [make_company("AAA", "up", "设备", also_in=["down"])]

    tree = build_tree(companies, LAYERS, "now")
    node = tree["root"]["children"][0]["children"][0]["children"][0]

    assert node["also_in"] == ["down"]
    assert node["cross_in"] == ["下游"]
    assert tree["stats"]["cross_layer"] == 1


def test_render_tree_contains_branches_and_cross_marker():
    companies = [
        make_company("AAA", "up", "设备", also_in=["down"]),
        make_company("BBB", "up", "材料"),
    ]

    text = render_tree(build_tree(companies, LAYERS, "now"))
    lines = text.splitlines()

    assert lines[0] == "AI 产业链 · AI Value Chain (2)"
    assert any("上游" in line and line.startswith("├──") for line in lines)
    assert any("BBB BBB Inc" in line for line in lines)
    assert "↔ 下游" in text


def test_render_mermaid_links_layers_segments_and_companies():
    companies = [
        make_company("AAA", "up", "设备", also_in=["down"]),
        make_company("BBB", "down", "应用"),
    ]

    text = render_mermaid(build_tree(companies, LAYERS, "now"))

    assert text.startswith("graph LR")
    assert 'R["AI 产业链 (2)"]' in text
    assert "R --> L0" in text
    assert "L0 --> L0S0" in text
    assert 'n_AAA["AAA AAA Inc"]' in text
    assert "n_AAA -.-> L1" in text


def test_render_mermaid_summary_omits_companies():
    companies = [make_company("AAA", "up", "设备")]

    text = render_mermaid(build_tree(companies, LAYERS, "now"), include_companies=False)

    assert "L0S0" in text
    assert "n_AAA" not in text


def test_main_writes_tree_json(tmp_path, monkeypatch):
    rows = [make_company("AAA", "up", "设备"), make_company("BBB", "down", "应用")]
    monkeypatch.setattr(
        ai_layers, "load_universe", lambda path=ai_layers.COMPANIES_PATH: (rows, LAYERS)
    )
    monkeypatch.setattr(ai_layers, "resolve_ciks", lambda companies, ticker_map=None: companies)
    out = tmp_path / "layers.json"

    ai_layers.main(["--out", str(out)])

    payload = json.loads(out.read_text())
    assert payload["stats"]["companies"] == 2
    assert payload["generated_at"]
    assert payload["source"] == "web/data/companies.json"


def test_enrich_graph_adds_layers_to_matching_nodes(tmp_path):
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "nodes": [{"id": 1, "ticker": "AAA"}, {"id": 99, "ticker": "GONE"}],
                "links": [{"source": 1, "target": 99}],
                "generated_at": "2026-01-01 00:00",
            },
            ensure_ascii=False,
        )
    )
    companies = [make_company("AAA", "up", "设备", cik=1, also_in=["down"])]

    updated = enrich_graph(companies, graph_path, layer_names={"up": "上游"})
    payload = json.loads(graph_path.read_text())

    assert updated == 1
    assert payload["nodes"][0]["layer"] == "up"
    assert payload["nodes"][0]["segment"] == "设备"
    assert payload["nodes"][0]["layer_name"] == "上游"
    assert payload["nodes"][0]["also_in"] == ["down"]
    assert "layer" not in payload["nodes"][1]
    assert payload["links"] == [{"source": 1, "target": 99}]

