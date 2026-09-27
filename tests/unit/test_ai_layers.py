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
    assert len(companies) >= 190
    assert len({company["ticker"] for company in companies}) == len(companies)
    for layer in layers:
        assert any(company["layer"] == layer["id"] for company in companies), layer["id"]
    app = next(layer for layer in layers if layer["id"] == "app")
    assert app["segments"] == [
        "企业软件与 Agent",
        "广告与营销 AI",
        "安全与身份",
        "消费与内容应用",
        "IT 服务与集成",
        "金融 AI",
        "医疗 AI 与计算生物",
        "客服与联络中心 AI",
        "AI 开发工具",
        "法律科技 AI",
        "垂直 SaaS AI",
        "国防与政府 AI",
    ]


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
    assert tree["stats"]["segments"] == 32
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
    assert payload["source"] == "data/ai_companies.json"

    assert not out.with_suffix(".js").exists()


def test_audit_graph_reports_missing_and_stale_nodes():
    graph = {
        "nodes": [{"id": 1, "ticker": "AAA"}, {"id": 99, "ticker": "GONE"}],
        "links": [{"source": 1, "target": 99}],
        "generated_at": "2026-01-01 00:00",
    }

    report = ai_layers.audit_graph(graph, ["AAA", "BBB"])

    assert report == {
        "nodes": 2,
        "links": 1,
        "matched": 1,
        "missing": ["BBB"],
        "stale": ["GONE"],
    }


def test_audit_graph_is_aligned_for_identical_sets():
    graph = {"nodes": [{"id": 1, "ticker": "aaa"}], "links": []}

    report = ai_layers.audit_graph(graph, ["AAA"])

    assert (report["matched"], report["missing"], report["stale"]) == (1, [], [])


def test_render_alignment_flags_missing_and_stale():
    status = ai_layers.render_alignment(
        {"nodes": 62, "links": 1199, "matched": 61, "missing": ["AAAA", "BBBB"], "stale": ["GONE"]}
    )

    assert status.splitlines()[0] == (
        "graph alignment: 61/63 universe tickers matched · 62 nodes · 1199 links"
    )
    assert "missing (2): AAAA, BBBB" in status
    assert "stale (1): GONE" in status


def test_main_exits_nonzero_when_graph_lags_universe(tmp_path, monkeypatch, capsys):
    rows = [make_company("AAA", "up", "设备", cik=1), make_company("BBB", "down", "应用", cik=2)]
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps({"nodes": [{"id": 1, "ticker": "AAA"}], "links": []}))
    monkeypatch.setattr(
        ai_layers, "load_universe", lambda path=ai_layers.COMPANIES_PATH: (rows, LAYERS)
    )
    monkeypatch.setattr(ai_layers, "resolve_ciks", lambda companies, ticker_map=None: companies)
    monkeypatch.setattr(ai_layers, "GRAPH_PATH", graph_path)

    with pytest.raises(SystemExit) as exit_info:
        ai_layers.main(["--out", str(tmp_path / "layers.json"), "--enrich-graph"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert "graph alignment: 1/2 universe tickers matched" in captured.out
    assert "missing (1): BBB" in captured.out
    assert "graph.json is out of sync" in captured.err


def test_main_allow_stale_graph_reports_but_exits_zero(tmp_path, monkeypatch, capsys):
    rows = [make_company("AAA", "up", "设备", cik=1), make_company("BBB", "down", "应用", cik=2)]
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps({"nodes": [{"id": 1, "ticker": "AAA"}], "links": []}))
    monkeypatch.setattr(
        ai_layers, "load_universe", lambda path=ai_layers.COMPANIES_PATH: (rows, LAYERS)
    )
    monkeypatch.setattr(ai_layers, "resolve_ciks", lambda companies, ticker_map=None: companies)
    monkeypatch.setattr(ai_layers, "GRAPH_PATH", graph_path)
    out = tmp_path / "layers.json"

    ai_layers.main(["--out", str(out), "--enrich-graph", "--allow-stale-graph"])

    captured = capsys.readouterr()
    assert "ignored by --allow-stale-graph" in captured.out
    assert captured.err == ""
    assert json.loads(out.read_text())["stats"]["companies"] == 2


def test_enrich_graph_requires_an_existing_graph(tmp_path):
    with pytest.raises(UniverseError, match="does not exist"):
        enrich_graph([make_company("AAA", "up", "设备")], tmp_path / "graph.json")


def test_real_graph_matches_universe():
    """The checked-in 3D graph must cover the curated universe, not a subset."""
    companies, _ = ai_layers.load_universe()

    report = ai_layers.audit_graph(
        json.loads(ai_layers.GRAPH_PATH.read_text()),
        [company["ticker"] for company in companies],
    )

    assert report["missing"] == []
    assert report["stale"] == []
    assert report["nodes"] == len(companies)


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
