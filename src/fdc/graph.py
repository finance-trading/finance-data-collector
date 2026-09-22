"""Build the tech-company relationship graph for the 3D viewer.

Reads web/data/companies.json (the curated universe, single source of truth),
resolves tickers to CIKs, derives three edge types, and writes
web/data/graph.json consumed by web/index.html.

Edge types:
- industry   : same GICS sub-industry (bounded K-nearest so meshes stay readable)
- crossref   : EDGAR full-text search — universe peers' 10-K filings mentioning this ticker
- coholding  : EDGAR 13F-HR — universe companies held by the same managers

Usage:
    uv run python -m fdc.graph
    uv run python -m fdc.graph --no-cohold
    uv run python -m fdc.graph --offline   # no network: industry edges only
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from fdc.sec_storage import CACHE_DIR, PROJECT_ROOT

WEB_DIR = PROJECT_ROOT / "web"
COMPANIES_PATH = WEB_DIR / "data" / "companies.json"
GRAPH_PATH = WEB_DIR / "data" / "graph.json"
TICKERS_CACHE = CACHE_DIR / "company_tickers.json"

DATA_SEC = "https://data.sec.gov"
EFTS = "https://efts.sec.gov/LATEST/search-index"
EDGAR_BROWSER = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"

DEFAULT_UA = "fdc-graph olijve@example.com"
ENV_VARS = ("FDC_SEC_USER_AGENT", "SEC_EDGAR_UA")


def user_agent() -> str:
    import os

    for var in ENV_VARS:
        if os.environ.get(var):
            return os.environ[var]
    cached = Path.home() / ".sec_edgar_user_agent"
    if cached.exists():
        return cached.read_text().strip()
    return DEFAULT_UA


def http_get_json(url: str, timeout: int = 30, retries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as exc:  # noqa: BLE001 - network layer, retry then surface
            last = exc
            time.sleep(1.0 * (2 ** attempt))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")


def load_ticker_cik_map() -> dict[str, int]:
    """ticker -> cik, from the local cache or EDGAR company_tickers.json."""
    if TICKERS_CACHE.exists():
        raw = json.loads(TICKERS_CACHE.read_text())
        rows = raw.values() if isinstance(raw, dict) else raw
        return {r["ticker"].upper(): int(r["cik_str"]) for r in rows if r.get("cik_str")}
    data = http_get_json(f"{DATA_SEC}/company_tickers.json")
    rows = data.values() if isinstance(data, dict) else data
    return {r["ticker"].upper(): int(r["cik_str"]) for r in rows if r.get("cik_str")}


def resolve_companies(universe: list[dict]) -> list[dict]:
    """Attach cik to each curated company; drop (with a warning) any unresolvable."""
    tmap = load_ticker_cik_map()
    out = []
    for c in universe:
        c["cik"] = tmap.get(c["ticker"].upper())
        if c["cik"] is None:
            print(f"  ! skipping {c['ticker']}: no CIK in ticker map")
        else:
            out.append(c)
    return out


def industry_edges(companies: list[dict], k: int = 3) -> list[dict]:
    """Within each sub-industry, link every company to its K nearest peers.

    Nearest = deterministic order by name, so a small group is a mesh and a
    large group stays bounded instead of a hairball.
    """
    by_ind: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in companies:
        by_ind[(c["sector"], c["industry"])].append(c)

    edges: dict[frozenset[int], dict] = {}
    for (_sector, industry), group in by_ind.items():
        group.sort(key=lambda c: c["name"])
        for i, c in enumerate(group):
            for j in list(range(i + 1, min(i + 1 + k, len(group)))):
                peer = group[j]
                key = frozenset((c["cik"], peer["cik"]))
                e = edges.get(key)
                if e is None:
                    e = edges[key] = {
                        "source": c["cik"],
                        "target": peer["cik"],
                        "type": "industry",
                        "weight": 1,
                        "desc": f"同 GICS 子行业：{industry}（{_sector}）",
                    }
                else:
                    e["weight"] += 1
    return list(edges.values())


def crossref_edges(
    companies: list[dict], count: int = 100, wait: float = 0.3
) -> list[dict]:
    """EFTS-search all universe 10-K filings for each company's ticker."""
    cik_set = {c["cik"] for c in companies}
    by_cik = {c["cik"]: c for c in companies}
    # mentions[me][other] = other's 10-K filings mention me's ticker
    mentions: dict[int, Counter] = defaultdict(Counter)

    for c in companies:
        q = c["ticker"] if len(c["ticker"]) >= 2 else c["name"]
        url = f"{EFTS}?q={urllib.parse.quote(q)}&forms=10-K&count={count}"
        try:
            data = http_get_json(url)
        except RuntimeError as exc:
            print(f"  ! crossref query failed for {c['ticker']}: {exc}")
            continue
        for hit in data.get("hits", {}).get("hits", []):
            for filer in hit.get("_source", {}).get("ciks", []):
                filer = int(filer)
                if filer in cik_set and filer != c["cik"]:
                    mentions[c["cik"]][filer] += 1
        time.sleep(wait)

    pairs: dict[frozenset[int], tuple[int, int]] = {}
    for me, counter in mentions.items():
        for other in counter:
            pairs.setdefault(frozenset((me, other)), (me, other))

    edges = []
    for key, (_me, _other) in pairs.items():
        a, b = sorted(key)
        parts = []
        if mentions[a].get(b):
            other, mine = by_cik[b]["ticker"], by_cik[a]["ticker"]
            parts.append(f"{other} 的 10-K 提及 {mine} {mentions[a][b]} 次")
        if mentions[b].get(a):
            other, mine = by_cik[a]["ticker"], by_cik[b]["ticker"]
            parts.append(f"{other} 的 10-K 提及 {mine} {mentions[b][a]} 次")
        edges.append({
            "source": a,
            "target": b,
            "type": "crossref",
            "weight": max(1, mentions[a].get(b, 0) + mentions[b].get(a, 0)),
            "desc": "申报文件互提及：" + "；".join(parts) if parts else "申报文件互提及（10-K）",
        })
    return edges


def cohold_edges(companies: list[dict], threshold: int = 2, wait: float = 0.3) -> list[dict]:
    """Shared 13F-HR managers between universe companies.

    EFTS name-inversion: search 13F-HR filings for each company's name ->
    the set of filing-manager CIKs; intersect per pair. No XML parsing.
    """
    holders: dict[int, set[int]] = {}
    for c in companies:
        url = f"{EFTS}?q={urllib.parse.quote(c['name'])}&forms=13F-HR&count=100"
        try:
            data = http_get_json(url)
        except RuntimeError as exc:
            print(f"  ! cohold query failed for {c['ticker']}: {exc}")
            holders[c["cik"]] = set()
            time.sleep(wait)
            continue
        managers = set()
        for hit in data.get("hits", {}).get("hits", []):
            for m in hit.get("_source", {}).get("ciks", []):
                managers.add(int(m))
        holders[c["cik"]] = managers
        time.sleep(wait)

    edges = []
    for i, a in enumerate(companies):
        for b in companies[i + 1:]:
            shared = holders[a["cik"]] & holders[b["cik"]]
            if len(shared) >= threshold:
                x, y = sorted((a["cik"], b["cik"]))
                edges.append({
                    "source": x,
                    "target": y,
                    "type": "coholding",
                    "weight": len(shared),
                    "desc": (
                        f"共同持仓：{len(shared)} 家机构在 13F 中同时持有 "
                        f"{by_ticker(companies, x)} 与 {by_ticker(companies, y)}"
                    ),
                })
    return edges


def by_ticker(companies: list[dict], cik: int) -> str:
    return next(c["ticker"] for c in companies if c["cik"] == cik)


def build(
    companies: list[dict],
    k_industry: int,
    include_crossref: bool,
    include_cohold: bool,
    wait: float,
) -> dict:
    nodes = [
        {
            "id": c["cik"],
            "ticker": c["ticker"],
            "name": c["name"],
            "sector": c["sector"],
            "industry": c["industry"],
            "layer": c.get("layer"),
            "segment": c.get("segment"),
            "description": c["description"],
            "edgar": EDGAR_BROWSER.format(cik=c["cik"]),
        }
        for c in companies
    ]

    links = industry_edges(companies, k=k_industry)
    seen_pairs = {frozenset((link["source"], link["target"])) for link in links}

    extra: list[dict] = []
    if include_crossref:
        print(f"crossref: {len(companies)} EFTS 10-K mention queries ...")
        extra.extend(
            edge
            for edge in crossref_edges(companies, wait=wait)
            if frozenset((edge["source"], edge["target"])) not in seen_pairs
        )
    if include_cohold:
        print(f"coholding: {len(companies)} EFTS 13F-HR holder queries ...")
        extra.extend(
            edge
            for edge in cohold_edges(companies, wait=wait)
            if frozenset((edge["source"], edge["target"])) not in seen_pairs
        )

    links.extend(extra)
    return {"nodes": nodes, "links": links, "generated_at": time.strftime("%Y-%m-%d %H:%M")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-crossref", action="store_true", help="skip 10-K mention queries")
    ap.add_argument("--no-cohold", action="store_true", help="skip 13F co-holding queries")
    ap.add_argument("--offline", action="store_true", help="no network: industry edges only")
    ap.add_argument(
        "--industry-neighbors",
        type=int,
        default=3,
        help="K nearest peers per company within a sub-industry",
    )
    ap.add_argument("--wait", type=float, default=0.3, help="seconds between EDGAR queries")
    args = ap.parse_args()

    companies = json.loads(COMPANIES_PATH.read_text())["companies"]
    print(f"universe: {len(companies)} companies")

    companies = resolve_companies(companies)
    print(f"resolved {len(companies)} tickers to CIK")

    graph = build(
        companies,
        k_industry=args.industry_neighbors,
        include_crossref=not args.offline and not args.no_crossref,
        include_cohold=not args.offline and not args.no_cohold,
        wait=args.wait,
    )
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=1))
    types = Counter(link["type"] for link in graph["links"])
    total = f"{len(graph['nodes'])} nodes, {len(graph['links'])} links, {dict(types)}"
    print(f"wrote {GRAPH_PATH} — {total}")


if __name__ == "__main__":
    main()
