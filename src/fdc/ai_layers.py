"""AI value-chain layering: company universe -> tree/graph data for the web viewers.

``web/data/companies.json`` stays the single source of truth:

- ``layers``   ordered upstream -> downstream AI value-chain layers.  Each layer
  declares the ``segments`` it contains, so rendering order never depends on the
  order of company rows.
- ``companies`` every row carries ``layer`` + ``segment``, and optionally
  ``also_in`` (layer ids) for companies that play a role in several layers.

This module validates that contract, resolves tickers to CIKs, and writes the
nested tree consumed by ``web/layers.html``:

    {"generated_at": ..., "stats": {...}, "root": {layer -> segment -> company}}

Usage:
    uv run python -m fdc.ai_layers                  # write web/data/layers.json
    uv run python -m fdc.ai_layers --tree           # ASCII tree to stdout
    uv run python -m fdc.ai_layers --mermaid        # mermaid graph to stdout
    uv run python -m fdc.ai_layers --enrich-graph   # copy layer/segment into graph.json

``--enrich-graph`` also audits the graph against the universe: when graph.json was
built before the universe grew (or still lists dropped tickers) the command prints
the offending ``missing`` / ``stale`` tickers and exits non-zero, so a stale graph
cannot ship silently.  Rebuild with ``fdc.graph`` (then enrich again), or pass
``--allow-stale-graph`` to inspect the drift anyway.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from fdc.graph import load_ticker_cik_map
from fdc.sec_storage import PROJECT_ROOT
from fdc.web_data import write_data

WEB_DIR = PROJECT_ROOT / "web"
DATA_DIR = WEB_DIR / "data"
COMPANIES_PATH = DATA_DIR / "companies.json"
LAYERS_PATH = DATA_DIR / "layers.json"
GRAPH_PATH = DATA_DIR / "graph.json"

REQUIRED_COMPANY_KEYS = ("ticker", "name", "sector", "industry", "layer", "segment", "description")
EDGAR_BROWSER = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
ROOT_ID = "ai"
ROOT_NAME = "AI 产业链"
ROOT_NAME_EN = "AI Value Chain"
GRAPH_STALE_HINT = (
    "graph.json is out of sync with the universe — rebuild it: "
    "uv run python -m fdc.graph && uv run python -m fdc.ai_layers --enrich-graph"
)


class UniverseError(ValueError):
    """Raised when companies.json violates the layering contract."""


def load_universe(path: Path | str = COMPANIES_PATH) -> tuple[list[dict], list[dict]]:
    """Read and validate companies.json; returns (companies, layers)."""
    payload = json.loads(Path(path).read_text())
    companies = payload["companies"]
    layers = payload["layers"]
    validate_universe(companies, layers)
    return companies, layers


def validate_universe(companies: list[dict], layers: list[dict]) -> None:
    """Enforce the layering contract; raise UniverseError on the first problem."""
    if not layers:
        raise UniverseError("universe must declare at least one layer")
    ids = [layer["id"] for layer in layers]
    if len(set(ids)) != len(ids):
        raise UniverseError(f"duplicate layer ids: {ids}")

    segments_of: dict[str, list[str]] = {}
    for layer in layers:
        if not layer.get("name") or not layer.get("segments"):
            raise UniverseError(f"layer {layer['id']!r} needs a name and at least one segment")
        segments_of[layer["id"]] = list(layer["segments"])

    known_layers = set(ids)
    seen: set[str] = set()
    used: dict[str, set[str]] = {layer_id: set() for layer_id in ids}

    for company in companies:
        ticker = company.get("ticker", "?")
        missing = [key for key in REQUIRED_COMPANY_KEYS if not company.get(key)]
        if missing:
            raise UniverseError(f"{ticker}: missing keys {missing}")
        if ticker.upper() in seen:
            raise UniverseError(f"duplicate ticker {ticker.upper()}")
        seen.add(ticker.upper())

        layer = company["layer"]
        if layer not in known_layers:
            known = sorted(known_layers)
            raise UniverseError(f"{ticker}: unknown layer {layer!r} (known: {known})")
        if company["segment"] not in segments_of[layer]:
            raise UniverseError(
                f"{ticker}: segment {company['segment']!r} is not declared by layer {layer!r} "
                f"(declared: {segments_of[layer]})"
            )
        used[layer].add(company["segment"])

        also_in = list(company.get("also_in", []))
        unknown_also = [layer_id for layer_id in also_in if layer_id not in known_layers]
        if unknown_also:
            raise UniverseError(f"{ticker}: unknown also_in layers {unknown_also}")
        if layer in also_in:
            raise UniverseError(f"{ticker}: also_in repeats its primary layer {layer!r}")

    for layer_id, declared in segments_of.items():
        empty = [name for name in declared if name not in used[layer_id]]
        if empty:
            raise UniverseError(f"layer {layer_id!r} declares empty segments {empty}")


def resolve_ciks(companies: list[dict], ticker_map: dict[str, int] | None = None) -> list[dict]:
    """Attach cik to each company; drop (with a warning) any unresolvable ticker."""
    tmap = load_ticker_cik_map() if ticker_map is None else ticker_map
    resolved = []
    for company in companies:
        cik = tmap.get(company["ticker"].upper())
        if cik is None:
            print(f"  ! skipping {company['ticker']}: no CIK in ticker map")
            continue
        resolved.append({**company, "cik": int(cik)})
    return resolved


def company_node(company: dict, layer_names: dict[str, str]) -> dict:
    """Leaf node: everything a viewer needs to draw and describe one company."""
    also_in = list(company.get("also_in", []))
    return {
        "id": company["ticker"].upper(),
        "type": "company",
        "ticker": company["ticker"].upper(),
        "name": company["name"],
        "cik": company["cik"],
        "sector": company["sector"],
        "industry": company["industry"],
        "layer": company["layer"],
        "segment": company["segment"],
        "description": company["description"],
        "also_in": also_in,
        "cross_in": [layer_names[layer_id] for layer_id in also_in],
        "edgar": EDGAR_BROWSER.format(cik=company["cik"]),
    }


def build_tree(companies: list[dict], layers: list[dict], generated_at: str) -> dict:
    """Nest companies as root -> layer -> segment -> company, in declared order.

    Company rows do not need to be grouped or sorted in the file: each one lands
    in its declared ``layer``/``segment``, and both orderings come from the
    ``layers`` spec, so the tree is stable regardless of file order.
    """
    layer_names = {layer["id"]: layer["name"] for layer in layers}
    grouped: dict[str, dict[str, list[dict]]] = {
        layer["id"]: {name: [] for name in layer["segments"]} for layer in layers
    }
    for company in companies:
        grouped[company["layer"]][company["segment"]].append(company_node(company, layer_names))

    layer_nodes = []
    for layer in layers:
        segments = [
            {
                "id": f"{layer['id']}/{name}",
                "type": "segment",
                "name": name,
                "layer": layer["id"],
                "count": len(grouped[layer["id"]][name]),
                "children": grouped[layer["id"]][name],
            }
            for name in layer["segments"]
        ]
        layer_nodes.append(
            {
                "id": layer["id"],
                "type": "layer",
                "name": layer["name"],
                "name_en": layer.get("name_en", ""),
                "summary": layer.get("summary", ""),
                "count": sum(segment["count"] for segment in segments),
                "children": segments,
            }
        )

    leaves = [
        node
        for layer in layer_nodes
        for segment in layer["children"]
        for node in segment["children"]
    ]
    stats = {
        "companies": len(leaves),
        "layers": len(layer_nodes),
        "segments": sum(len(layer["children"]) for layer in layer_nodes),
        "cross_layer": sum(len(node["also_in"]) for node in leaves),
    }
    return {
        "generated_at": generated_at,
        "source": "web/data/companies.json",
        "stats": stats,
        "root": {
            "id": ROOT_ID,
            "type": "root",
            "name": ROOT_NAME,
            "name_en": ROOT_NAME_EN,
            "count": stats["companies"],
            "children": layer_nodes,
        },
    }


def render_tree(tree: dict) -> str:
    """ASCII tree, one company per line; ``↔`` marks cross-layer roles."""
    root = tree["root"]
    lines = [f"{root['name']} · {root['name_en']} ({root['count']})"]
    children = root["children"]
    for layer_index, layer in enumerate(children):
        is_last_layer = layer_index == len(children) - 1
        title = f"{layer['name']} · {layer['name_en']} ({layer['count']})"
        lines.append(f"{'└──' if is_last_layer else '├──'} {title}")
        layer_pad = "    " if is_last_layer else "│   "
        segments = layer["children"]
        for segment_index, segment in enumerate(segments):
            is_last_segment = segment_index == len(segments) - 1
            head = f"{segment['name']} ({segment['count']})"
            lines.append(f"{layer_pad}{'└──' if is_last_segment else '├──'} {head}")
            segment_pad = layer_pad + ("    " if is_last_segment else "│   ")
            nodes = segment["children"]
            for node_index, node in enumerate(nodes):
                is_last_node = node_index == len(nodes) - 1
                cross = f"  ↔ {'/'.join(node['cross_in'])}" if node["cross_in"] else ""
                body = f"{node['ticker']} {node['name']} — {node['description']}{cross}"
                lines.append(f"{segment_pad}{'└──' if is_last_node else '├──'} {body}")
    return "\n".join(lines)


def mermaid_id(value: str) -> str:
    """Mermaid-safe node id."""
    return "n_" + "".join(char if char.isalnum() else "_" for char in value)


def render_mermaid(tree: dict, include_companies: bool = True) -> str:
    """Mermaid ``graph LR``: layers -> segments -> companies, dashed cross-layer edges."""
    root = tree["root"]
    index_of = {layer["id"]: index for index, layer in enumerate(root["children"])}
    lines = ["graph LR", f'  R["{root["name"]} ({root["count"]})"]']
    cross_edges: list[str] = []
    for layer_index, layer in enumerate(root["children"]):
        layer_id = f"L{layer_index}"
        head = f"{layer['name']} · {layer['name_en']} ({layer['count']})"
        lines.append(f'  {layer_id}["{head}"]')
        lines.append(f"  R --> {layer_id}")
        for segment_index, segment in enumerate(layer["children"]):
            segment_id = f"{layer_id}S{segment_index}"
            lines.append(f'  {segment_id}["{segment["name"]} ({segment["count"]})"]')
            lines.append(f"  {layer_id} --> {segment_id}")
            if not include_companies:
                continue
            for node in segment["children"]:
                node_id = mermaid_id(node["ticker"])
                lines.append(f'  {node_id}["{node["ticker"]} {node["name"]}"]')
                lines.append(f"  {segment_id} --> {node_id}")
                for other in node["also_in"]:
                    cross_edges.append(f"  {node_id} -.-> L{index_of[other]}")
    return "\n".join(lines + cross_edges)


def enrich_graph(
    companies: list[dict],
    graph_path: Path | str = GRAPH_PATH,
    layer_names: dict[str, str] | None = None,
) -> int:
    """Copy layer/segment onto the matching graph.json nodes; existing edges are kept.

    ``layer_names`` maps layer id -> display name, so the 3D viewer can group and
    label nodes without re-reading companies.json.
    """
    path = Path(graph_path)
    if not path.exists():
        raise UniverseError(f"{path} does not exist — build it first: uv run python -m fdc.graph")
    payload = json.loads(path.read_text())
    names = layer_names or {}
    by_cik = {company["cik"]: company for company in companies}
    updated = 0
    for node in payload["nodes"]:
        company = by_cik.get(int(node["id"]))
        if company is None:
            stale = node.get("ticker", node["id"])
            print(f"  ! graph.json node {stale} is not in the universe (rebuild it: fdc.graph)")
            continue
        node["layer"] = company["layer"]
        node["segment"] = company["segment"]
        node["layer_name"] = names.get(company["layer"], company["layer"])
        if company.get("also_in"):
            node["also_in"] = list(company["also_in"])
        updated += 1
    write_data(path.stem, payload, path.parent)
    return updated


def audit_graph(graph: dict, tickers: list[str]) -> dict:
    """Compare a graph.json payload with the universe tickers.

    ``missing`` are universe tickers the graph does not carry (the graph predates
    them), ``stale`` are graph tickers that left the universe.  Both empty means
    the graph is aligned and can be published.
    """
    expected = {str(ticker).upper() for ticker in tickers}
    present = {str(node.get("ticker", node["id"])).upper() for node in graph.get("nodes", [])}
    return {
        "nodes": len(graph.get("nodes", [])),
        "links": len(graph.get("links", [])),
        "matched": len(expected & present),
        "missing": sorted(expected - present),
        "stale": sorted(present - expected),
    }


def _ticker_preview(tickers: list[str], limit: int = 8) -> str:
    """Comma-joined first ``limit`` tickers, then a ``+n more`` suffix."""
    head = ", ".join(tickers[:limit])
    rest = len(tickers) - limit
    return f"{head}, … (+{rest})" if rest > 0 else head


def render_alignment(report: dict) -> str:
    """One-line graph/universe alignment summary plus offending tickers."""
    total = report["matched"] + len(report["missing"])
    lines = [
        f"graph alignment: {report['matched']}/{total} universe tickers matched · "
        f"{report['nodes']} nodes · {report['links']} links"
    ]
    if report["missing"]:
        lines.append(f"  missing ({len(report['missing'])}): {_ticker_preview(report['missing'])}")
    if report["stale"]:
        lines.append(f"  stale ({len(report['stale'])}): {_ticker_preview(report['stale'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build the AI value-chain layer tree from web/data/companies.json."
    )
    parser.add_argument(
        "--out", type=Path, default=LAYERS_PATH, help="output path for the tree JSON"
    )
    parser.add_argument("--tree", action="store_true", help="print an ASCII tree to stdout")
    parser.add_argument("--mermaid", action="store_true", help="print a mermaid graph to stdout")
    parser.add_argument(
        "--mermaid-summary", action="store_true", help="mermaid output stops at segment level"
    )
    parser.add_argument(
        "--enrich-graph",
        action="store_true",
        help="also copy layer/segment into web/data/graph.json",
    )
    parser.add_argument(
        "--allow-stale-graph",
        action="store_true",
        help="report a graph.json that lags the universe but still exit 0",
    )
    args = parser.parse_args(argv)

    companies, layers = load_universe()
    print(f"universe: {len(companies)} companies · {len(layers)} layers")
    resolved = resolve_ciks(companies)
    tree = build_tree(resolved, layers, time.strftime("%Y-%m-%d %H:%M"))
    json_path, js_path = write_data(args.out.stem, tree, args.out.parent)

    stats = tree["stats"]
    print(
        f"wrote {json_path} + {js_path.name} — {stats['companies']} companies · "
        f"{stats['layers']} layers · {stats['segments']} segments · "
        f"{stats['cross_layer']} cross-layer roles"
    )
    stale_graph = False
    if args.enrich_graph:
        names = {layer["id"]: layer["name"] for layer in layers}
        enriched = enrich_graph(resolved, graph_path=GRAPH_PATH, layer_names=names)
        print(f"enriched {enriched} matching nodes in {GRAPH_PATH}")
        report = audit_graph(
            json.loads(Path(GRAPH_PATH).read_text()),
            [company["ticker"] for company in resolved],
        )
        print(render_alignment(report))
        stale_graph = bool(report["missing"] or report["stale"])
        if stale_graph and args.allow_stale_graph:
            print("  ! stale graph.json ignored by --allow-stale-graph")
    if args.tree:
        print(render_tree(tree))
    if args.mermaid:
        print(render_mermaid(tree, include_companies=not args.mermaid_summary))
    if stale_graph and not args.allow_stale_graph:
        print(f"  ! {GRAPH_STALE_HINT}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()


