"""Unit tests for the relationship graph builder.

Everything here runs offline: EDGAR replies are replaced by stubbed EFTS
payloads, so parsing, filtering and caching are covered without touching the
network. One test re-checks the checked-in graph.json artifact.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from fdc import graph
from fdc.graph import (
    GRAPH_PATH,
    build,
    cap_neighbors,
    cohold_edges,
    crossref_edges,
    efts_cache_path,
    fetch_efts,
    industry_edges,
    pair_key,
)


def make_company(ticker, cik, name=None, **extra):
    row = {
        "ticker": ticker,
        "name": name or f"{ticker} Holdings Inc",
        "sector": "Technology",
        "industry": "Semiconductors",
        "description": f"{ticker} 描述。",
        "cik": cik,
    }
    row.update(extra)
    return row


def efts_payload(*ciks):
    """Minimal EFTS response shape: hits -> _source -> ciks."""
    return {"hits": {"hits": [{"_source": {"ciks": [str(c) for c in ciks]}}]}}


def query_of(url: str) -> str:
    """The q= value of an EFTS query URL, with '+' restored to spaces."""
    params = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
    return params["q"].replace("+", " ")


def degrees(edges):
    counts: dict[int, int] = {}
    for edge in edges:
        counts[edge["source"]] = counts.get(edge["source"], 0) + 1
        counts[edge["target"]] = counts.get(edge["target"], 0) + 1
    return counts


# --- cap_neighbors ---------------------------------------------------------


def star_edges(hub=1, spokes=6, hub_weight=10):
    """Hub connected to `spokes` leaves; the leaves only know the hub."""
    return [
        {
            "source": hub,
            "target": 100 + i,
            "type": "coholding",
            "weight": hub_weight - i,
            "desc": f"hub-{100 + i}",
        }
        for i in range(spokes)
    ]


def test_cap_neighbors_disabled_keeps_everything():
    edges = star_edges()

    assert cap_neighbors(edges, 0) == edges
    assert cap_neighbors(edges, -2) == edges


def test_cap_neighbors_bounds_every_degree():
    kept = cap_neighbors(star_edges(spokes=8), 3)

    assert max(degrees(kept).values()) <= 3
    assert kept, "the strongest reciprocal links must survive"


def test_cap_neighbors_keeps_only_reciprocal_strongest():
    # Hub ranks every leaf and each leaf only ranks the hub.
    assert len(cap_neighbors(star_edges(spokes=4), 4)) == 4  # all four fit in k
    assert len(cap_neighbors(star_edges(spokes=4), 1)) == 1  # hub keeps its best partner

    # Two hubs share the same leaves; each leaf keeps only its single best link.
    edges = [
        {"source": 1, "target": 9, "type": "coholding", "weight": 5, "desc": "a"},
        {"source": 2, "target": 9, "type": "coholding", "weight": 7, "desc": "b"},
        {"source": 1, "target": 8, "type": "coholding", "weight": 6, "desc": "c"},
        {"source": 2, "target": 8, "type": "coholding", "weight": 4, "desc": "d"},
    ]

    kept = cap_neighbors(edges, 1)

    # Node 9 keeps (2,9) and node 8 keeps (1,8); hub 1 drops (1,9) because (1,8)
    # outranks it, so only the two reciprocal winners remain.
    assert sorted(pair_key(e) for e in kept) == [(1, 8), (2, 9)]


def test_cap_neighbors_is_order_independent():
    edges = star_edges(spokes=8)
    shuffled = [edges[i] for i in (3, 0, 7, 1, 6, 2, 5, 4)]

    assert sorted(map(pair_key, cap_neighbors(edges, 4))) == sorted(
        map(pair_key, cap_neighbors(shuffled, 4))
    )


# --- industry_edges --------------------------------------------------------


def test_industry_edges_bucket_by_gics_first():
    companies = [
        make_company("AAA", 1, name="Alpha", sector="Technology", industry="Semiconductors",
                     layer="silicon", segment="算力芯片"),
        make_company("BBB", 2, name="Bravo", sector="Technology", industry="Semiconductors",
                     layer="silicon", segment="算力芯片"),
        # Charlie is alone in its GICS industry but not in its layer segment.
        make_company("CCC", 3, name="Charlie", sector="Utilities", industry="Power Producers",
                     layer="power", segment="发电与核电"),
        make_company("DDD", 4, name="Delta", sector="Utilities", industry="Water Utilities",
                     layer="power", segment="发电与核电"),
    ]

    edges = industry_edges(
        companies, k=3, layer_names={"silicon": "芯片与半导体", "power": "能源与电力"}
    )

    assert {pair_key(e): e["desc"] for e in edges} == {
        (1, 2): "同 GICS 子行业：Semiconductors（Technology）",
        (3, 4): "同分层环节：发电与核电（能源与电力）",
    }


def test_industry_edges_fall_back_to_layer_for_lonely_companies():
    companies = [
        make_company("AAA", 1, name="Alpha", sector="Technology", industry="Semis",
                     layer="silicon", segment="算力芯片"),
        make_company("BBB", 2, name="Bravo", sector="Technology", industry="Semis",
                     layer="silicon", segment="算力芯片"),
        make_company("PWR", 3, name="Quanta", sector="Industrials", industry="Construction",
                     layer="power", segment="电网与工程"),
        make_company("AES", 4, name="AES Corp", sector="Utilities", industry="Power",
                     layer="power", segment="发电与核电"),
    ]

    edges = industry_edges(
        companies, k=3, layer_names={"power": "能源与电力", "silicon": "芯片与半导体"}
    )

    assert sorted(pair_key(e) for e in edges) == [(1, 2), (3, 4)]
    fallback = next(e for e in edges if pair_key(e) == (3, 4))
    assert fallback["desc"] == "同分层：能源与电力"

    # Nothing is left floating: every company carries at least one edge.
    assert min(degrees(edges).values()) >= 1


def test_industry_edges_rescues_a_company_alone_in_every_bucket():
    companies = [
        make_company("AAA", 1, name="Alpha", sector="Technology", industry="Semis",
                     layer="silicon", segment="算力芯片"),
        make_company("BBB", 2, name="Bravo", sector="Technology", industry="Semis",
                     layer="silicon", segment="算力芯片"),
        # KEYS stands alone in its GICS industry and in its own segment.
        make_company("KEYS", 3, name="Keysight", sector="Technology",
                     industry="Electronic Equipment", layer="silicon", segment="测试测量"),
    ]

    edges = industry_edges(companies, k=1, layer_names={"silicon": "芯片与半导体"})

    assert min(degrees(edges).values()) >= 1
    rescued = [e for e in edges if 3 in (e["source"], e["target"])]
    assert rescued[0]["desc"] == "同分层：芯片与半导体"


def test_industry_edges_prefers_segment_over_whole_layer():
    companies = [
        make_company("AAA", 1, name="Alpha", sector="Industrials", industry="Construction",
                     layer="power", segment="电网与工程"),
        make_company("BBB", 2, name="Bravo", sector="Utilities", industry="Power",
                     layer="power", segment="电网与工程"),
    ]

    edges = industry_edges(companies, k=3, layer_names={"power": "能源与电力"})

    assert edges[0]["desc"] == "同分层环节：电网与工程（能源与电力）"


# --- EFTS cache ------------------------------------------------------------


def test_efts_cache_path_is_readable_and_unique():
    base = "https://efts.sec.gov/LATEST/search-index?"
    a = efts_cache_path(f"{base}q=NVIDIA+Corp&forms=13F-HR")
    b = efts_cache_path(f"{base}q=NVIDIA+Corp&forms=10-K")
    c = efts_cache_path(f"{base}q=AMD&forms=13F-HR")

    assert a.name.startswith("13f-hr-nvidia-corp-")
    assert len({a.name, b.name, c.name}) == 3


def test_fetch_efts_caches_and_refresh_bypasses(monkeypatch, tmp_path):
    monkeypatch.setattr(graph, "EFTS_CACHE", tmp_path)
    calls = []

    def fake_get(url, timeout=30, retries=3):
        calls.append(url)
        return efts_payload(42)

    monkeypatch.setattr(graph, "http_get_json", fake_get)
    url = "https://efts.sec.gov/LATEST/search-index?q=NVIDIA&forms=13F-HR&count=100"

    first, cached_first = fetch_efts(url)
    second, cached_second = fetch_efts(url)
    third, cached_third = fetch_efts(url, refresh=True)

    assert first == second == third == efts_payload(42)
    assert (cached_first, cached_second, cached_third) == (False, True, False)
    assert len(calls) == 2
    assert len(list(tmp_path.glob("*.json"))) == 1


# --- crossref_edges --------------------------------------------------------


def test_crossref_edges_reads_mentions_both_ways(monkeypatch):
    companies = [
        make_company("AAA", 1),
        make_company("BBB", 2),
        make_company("CCC", 3),
    ]
    # AAA's 10-K mentions BBB, BBB's mentions AAA, nobody mentions CCC.
    mentions = {"AAA": (2,), "BBB": (1,), "CCC": (9,)}
    monkeypatch.setattr(
        graph,
        "fetch_efts",
        lambda url, refresh=False: (efts_payload(*mentions[query_of(url)]), False),
    )

    edges = crossref_edges(companies, wait=0.0)

    assert len(edges) == 1
    edge = edges[0]
    assert pair_key(edge) == (1, 2)
    assert edge["type"] == "crossref"
    assert edge["weight"] == 2
    assert "AAA" in edge["desc"] and "BBB" in edge["desc"]


# --- cohold_edges ----------------------------------------------------------


def cohold_stub(holders_by_name):
    """Stub EFTS fetch: company name query -> holder CIKs."""

    def fake_fetch(url, refresh=False):
        return efts_payload(*holders_by_name[query_of(url)]), False

    return fake_fetch


def test_cohold_edges_thresholds_and_caps(monkeypatch):
    companies = [
        make_company("AAA", 1, name="Alpha Corp"),
        make_company("BBB", 2, name="Bravo Corp"),
        make_company("CCC", 3, name="Charlie Corp"),
    ]
    # AAA/BBB share three managers; the others share only one.
    holders = {
        "Alpha Corp": (10, 11, 12),
        "Bravo Corp": (10, 11, 12),
        "Charlie Corp": (10, 99),
    }
    monkeypatch.setattr(graph, "fetch_efts", cohold_stub(holders))

    edges = cohold_edges(companies, min_shared=3, neighbors=5, wait=0.0)

    assert [pair_key(e) for e in edges] == [(1, 2)]
    assert edges[0]["type"] == "coholding"
    assert edges[0]["weight"] == 3
    assert "3 家机构" in edges[0]["desc"]

    # A looser threshold lets the weak pairs through again.
    assert len(cohold_edges(companies, min_shared=1, neighbors=5, wait=0.0)) == 3


def test_cohold_edges_applies_neighbor_cap(monkeypatch):
    companies = [make_company(t, i + 1, name=f"{t} Corp") for i, t in enumerate("ABCDE")]
    holders = {f"{t} Corp": (1, 2, 3) for t in "ABCDE"}
    monkeypatch.setattr(graph, "fetch_efts", cohold_stub(holders))

    uncapped = cohold_edges(companies, min_shared=3, neighbors=0, wait=0.0)
    capped = cohold_edges(companies, min_shared=3, neighbors=2, wait=0.0)

    assert len(uncapped) == 10  # complete graph over five companies
    assert max(degrees(capped).values()) <= 2
    assert len(capped) < len(uncapped)


def test_cohold_edges_skips_the_sleep_on_cache_hits(monkeypatch):
    companies = [make_company("AAA", 1, name="Alpha Corp")]
    monkeypatch.setattr(graph, "fetch_efts", lambda url, refresh=False: (efts_payload(1), True))
    slept = []
    monkeypatch.setattr(graph.time, "sleep", slept.append)

    cohold_edges(companies, min_shared=1, neighbors=0, wait=0.3)

    assert slept == []


# --- build() integration ---------------------------------------------------


def test_build_industry_only_writes_expected_shape():
    companies = [
        make_company("AAA", 1, name="Alpha", layer="silicon", segment="算力芯片"),
        make_company("BBB", 2, name="Bravo", layer="silicon", segment="算力芯片"),
    ]

    graph_data = build(
        companies,
        k_industry=3,
        include_crossref=False,
        include_cohold=False,
        wait=0.0,
    )

    assert {node["ticker"] for node in graph_data["nodes"]} == {"AAA", "BBB"}
    assert graph_data["nodes"][0]["layer"] == "silicon"
    assert graph_data["nodes"][0]["edgar"].endswith("CIK=1")
    assert [link["type"] for link in graph_data["links"]] == ["industry"]


# --- checked-in artifact ---------------------------------------------------


@pytest.mark.skipif(not GRAPH_PATH.exists(), reason="graph.json not built yet")
def test_real_graph_leaves_no_node_isolated():
    """Every curated company must carry at least one edge in the 3D view."""
    graph_data = json.loads(GRAPH_PATH.read_text())
    number_of = degrees(graph_data["links"])
    isolated = [n["ticker"] for n in graph_data["nodes"] if not number_of.get(n["id"])]

    assert isolated == []


@pytest.mark.skipif(not GRAPH_PATH.exists(), reason="graph.json not built yet")
def test_real_graph_cohold_edges_respect_the_cap():
    """The 13F overlay must stay readable: no hairball in the checked-in graph."""
    graph_data = json.loads(GRAPH_PATH.read_text())
    cohold = [link for link in graph_data["links"] if link["type"] == "coholding"]

    if not cohold:
        pytest.skip("coholding edges disabled in the current graph")

    assert max(degrees(cohold).values()) <= 5
    assert min(link["weight"] for link in cohold) >= 8
    assert len(cohold) <= len(graph_data["nodes"]) * 2
