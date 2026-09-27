"""Build the tech-company relationship graph for the 3D viewer.

Reads data/ai_companies.json (the curated universe, single source of truth),
resolves tickers to CIKs, derives three edge types, and writes
data/generated/graph.json for the read API.

Edge types:
- industry   : same GICS sub-industry (bounded K-nearest so meshes stay readable)
- crossref   : EDGAR full-text search — universe peers' 10-K filings mentioning this ticker
- coholding  : EDGAR 13F-HR — universe companies held by the same managers. Raw overlap is
               index-fund noise (7.5k edges, median shared managers 3, max 19), so pairs
               need --cohold-min-shared managers and are capped to --cohold-neighbors
               reciprocal strongest partners.

EFTS responses are cached under sec/.cache/efts, so re-runs are instant and offline;
pass --refresh-cache to query EDGAR again.

Usage:
    uv run python -m fdc.graph
    uv run python -m fdc.graph --no-cohold
    uv run python -m fdc.graph --offline   # no network: industry edges only
    uv run python -m fdc.graph --refresh-cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from fdc.data_files import CATALOG_PATH, GRAPH_PATH, write_json_artifact
from fdc.sec_storage import CACHE_DIR

COMPANIES_PATH = CATALOG_PATH
TICKERS_CACHE = CACHE_DIR / "company_tickers.json"
EFTS_CACHE = CACHE_DIR / "efts"

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


def efts_cache_path(url: str) -> Path:
    """Deterministic, human-inspectable cache filename for one EFTS query."""
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    label = f"{params.get('forms', 'q')}-{params.get('q', '')}"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower()[:60]
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    return EFTS_CACHE / f"{slug}-{digest}.json"


def fetch_efts(url: str, refresh: bool = False) -> tuple[dict, bool]:
    """Return (payload, from_cache) for an EFTS query, caching the response on disk."""
    path = efts_cache_path(url)
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text()), True
        except json.JSONDecodeError:
            print(f"  ! ignoring corrupt cache file {path.name}")
    data = http_get_json(url)
    EFTS_CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data, False


def pair_key(edge: dict) -> tuple[int, int]:
    """Order-independent identity of an edge, for dedup and ranking."""
    return tuple(sorted((edge["source"], edge["target"])))


def cap_neighbors(edges: list[dict], k: int) -> list[dict]:
    """Keep only edges that both endpoints rank among their K strongest.

    Reciprocal-only keeps every node's degree <= k, which is what stops 13F
    co-holding from turning the 3D view into a hairball. Ties break on the
    endpoint pair, so the result is deterministic. k <= 0 disables the cap.
    """
    if k <= 0:
        return edges

    incident: dict[int, list[dict]] = defaultdict(list)
    for edge in edges:
        incident[edge["source"]].append(edge)
        incident[edge["target"]].append(edge)

    def rank(edge: dict) -> tuple[int, int, int]:
        a, b = pair_key(edge)
        return (-edge["weight"], a, b)

    keep = {
        node: {pair_key(edge) for edge in sorted(group, key=rank)[:k]}
        for node, group in incident.items()
    }
    return [
        edge
        for edge in edges
        if pair_key(edge) in keep[edge["source"]] and pair_key(edge) in keep[edge["target"]]
    ]


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


def add_industry_edge(
    edges: dict[frozenset[int], dict],
    a: dict,
    b: dict,
    label: str,
    detail: str,
) -> None:
    """Record one derived industry link, counting repeats as extra weight."""
    key = frozenset((a["cik"], b["cik"]))
    edge = edges.get(key)
    if edge is None:
        x, y = sorted((a["cik"], b["cik"]))
        edges[key] = {
            "source": x,
            "target": y,
            "type": "industry",
            "weight": 1,
            "desc": f"{label}：{detail}",
        }
    else:
        edge["weight"] += 1


def nearest_names(group: list[dict], company: dict, k: int) -> list[dict]:
    """The K companies closest to `company` in a name-sorted bucket."""
    ordered = sorted(group, key=lambda c: c["name"])
    index = next(i for i, c in enumerate(ordered) if c["cik"] == company["cik"])
    after = ordered[index + 1 : index + 1 + k]
    before = list(reversed(ordered[max(0, index - k) : index]))
    return (after + before)[:k]


def link_group(
    group: list[dict],
    k: int,
    label: str,
    detail: str,
    edges: dict[frozenset[int], dict],
) -> None:
    """Mesh a bucket: every member links to its K next neighbours (by name)."""
    for i, c in enumerate(group):
        for peer in group[i + 1 : i + 1 + k]:
            add_industry_edge(edges, c, peer, label, detail)


def industry_edges(
    companies: list[dict],
    k: int = 3,
    layer_names: dict[str, str] | None = None,
) -> list[dict]:
    """Link each company to its K nearest peers at the finest level that works.

    Level 1 buckets by GICS (sector, industry), then any company still without a
    peer falls back to (layer, segment) and finally to the layer, so no curated
    company floats unconnected in the 3D view. A company that is alone in every
    bucket (KEYS sits alone in its GICS industry) is linked to the nearest names
    of its layer instead. Within a bucket "nearest" is deterministic by name, so
    a small group is a mesh and a large group stays bounded instead of a hairball.
    """
    names = layer_names or {}
    edges: dict[frozenset[int], dict] = {}
    connected: set[int] = set()

    levels = (
        (
            "同 GICS 子行业",
            lambda c: (c["sector"], c["industry"]),
            lambda c: f"{c['industry']}（{c['sector']}）",
        ),
        (
            "同分层环节",
            lambda c: (c.get("layer"), c.get("segment")),
            lambda c: f"{c.get('segment')}（{names.get(c.get('layer'), c.get('layer'))}）",
        ),
        (
            "同分层",
            lambda c: c.get("layer"),
            lambda c: str(names.get(c.get("layer"), c.get("layer"))),
        ),
    )

    for label, bucket_of, detail_of in levels:
        buckets: dict[object, list[dict]] = defaultdict(list)
        for c in companies:
            if c["cik"] not in connected:
                buckets[bucket_of(c)].append(c)
        for group in buckets.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda c: c["name"])
            link_group(group, k, label, detail_of(group[0]), edges)
            connected.update(c["cik"] for c in group)

    for c in [c for c in companies if c["cik"] not in connected]:
        for label, bucket_of, detail_of in levels:
            bucket = [o for o in companies if bucket_of(o) == bucket_of(c)]
            if len(bucket) < 2:
                continue
            for peer in nearest_names(bucket, c, k):
                add_industry_edge(edges, c, peer, label, detail_of(c))
            connected.add(c["cik"])
            break
    return list(edges.values())


def crossref_edges(
    companies: list[dict],
    count: int = 100,
    wait: float = 0.3,
    refresh: bool = False,
) -> list[dict]:
    """EFTS-search all universe 10-K filings for each company's ticker."""
    cik_set = {c["cik"] for c in companies}
    by_cik = {c["cik"]: c for c in companies}
    # mentions[me][other] = other's 10-K filings mention me's ticker
    mentions: dict[int, Counter] = defaultdict(Counter)
    fetched = 0

    for c in companies:
        q = c["ticker"] if len(c["ticker"]) >= 2 else c["name"]
        url = f"{EFTS}?q={urllib.parse.quote(q)}&forms=10-K&count={count}"
        try:
            data, cached = fetch_efts(url, refresh)
        except RuntimeError as exc:
            print(f"  ! crossref query failed for {c['ticker']}: {exc}")
            continue
        if not cached:
            fetched += 1
            time.sleep(wait)
        for hit in data.get("hits", {}).get("hits", []):
            for filer in hit.get("_source", {}).get("ciks", []):
                filer = int(filer)
                if filer in cik_set and filer != c["cik"]:
                    mentions[c["cik"]][filer] += 1
    print(f"  crossref: {fetched}/{len(companies)} queries fetched from EDGAR (rest cached)")

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


def cohold_edges(
    companies: list[dict],
    min_shared: int = 8,
    neighbors: int = 5,
    wait: float = 0.3,
    refresh: bool = False,
) -> list[dict]:
    """Shared 13F-HR managers between universe companies.

    EFTS name-inversion: search 13F-HR filings for each company's name ->
    the set of filing-manager CIKs; intersect per pair. No XML parsing.

    Overlap counts filings that mention both names, so index-style managers that
    file for every large cap make every pair overlap a little. Pairs therefore
    need `min_shared` managers and then survive only if both endpoints rank each
    other among their `neighbors` strongest partners (`neighbors=0` disables).
    """
    holders: dict[int, set[int]] = {}
    fetched = 0
    for c in companies:
        url = f"{EFTS}?q={urllib.parse.quote(c['name'])}&forms=13F-HR&count=100"
        try:
            data, cached = fetch_efts(url, refresh)
        except RuntimeError as exc:
            print(f"  ! cohold query failed for {c['ticker']}: {exc}")
            holders[c["cik"]] = set()
            time.sleep(wait)
            continue
        if not cached:
            fetched += 1
            time.sleep(wait)
        managers = set()
        for hit in data.get("hits", {}).get("hits", []):
            for m in hit.get("_source", {}).get("ciks", []):
                managers.add(int(m))
        holders[c["cik"]] = managers
    print(f"  coholding: {fetched}/{len(companies)} queries fetched from EDGAR (rest cached)")

    candidates = []
    for i, a in enumerate(companies):
        for b in companies[i + 1:]:
            shared = holders[a["cik"]] & holders[b["cik"]]
            if len(shared) >= min_shared:
                x, y = sorted((a["cik"], b["cik"]))
                candidates.append({
                    "source": x,
                    "target": y,
                    "type": "coholding",
                    "weight": len(shared),
                    "desc": (
                        f"共同持仓：{len(shared)} 家机构在 13F 中同时持有 "
                        f"{by_ticker(companies, x)} 与 {by_ticker(companies, y)}"
                    ),
                })

    kept = cap_neighbors(candidates, neighbors)
    dropped = len(candidates) - len(kept)
    print(
        f"  coholding: {len(candidates)} pairs share >= {min_shared} managers, "
        f"{len(kept)} kept (dropped {dropped} one-sided strongest)"
    )
    return kept


def by_ticker(companies: list[dict], cik: int) -> str:
    return next(c["ticker"] for c in companies if c["cik"] == cik)


def build(
    companies: list[dict],
    k_industry: int,
    include_crossref: bool,
    include_cohold: bool,
    wait: float,
    cohold_min_shared: int = 8,
    cohold_neighbors: int = 5,
    refresh_cache: bool = False,
    layer_names: dict[str, str] | None = None,
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

    links = industry_edges(companies, k=k_industry, layer_names=layer_names)
    seen_pairs = {pair_key(link) for link in links}

    extra: list[dict] = []
    if include_crossref:
        print(f"crossref: {len(companies)} EFTS 10-K mention queries ...")
        extra.extend(
            edge
            for edge in crossref_edges(companies, wait=wait, refresh=refresh_cache)
            if pair_key(edge) not in seen_pairs
        )
    if include_cohold:
        print(f"coholding: {len(companies)} EFTS 13F-HR holder queries ...")
        extra.extend(
            edge
            for edge in cohold_edges(
                companies,
                min_shared=cohold_min_shared,
                neighbors=cohold_neighbors,
                wait=wait,
                refresh=refresh_cache,
            )
            if pair_key(edge) not in seen_pairs
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
        help=(
            "K nearest peers per company; buckets fall back from GICS sub-industry "
            "to layer segment to layer so nobody is left isolated"
        ),
    )
    ap.add_argument(
        "--cohold-min-shared",
        type=int,
        default=8,
        help="keep 13F pairs sharing at least this many managers (default 8)",
    )
    ap.add_argument(
        "--cohold-neighbors",
        type=int,
        default=5,
        help="cap each company to its K strongest reciprocal 13F partners, 0 = no cap",
    )
    ap.add_argument(
        "--refresh-cache",
        action="store_true",
        help="re-query EDGAR instead of reading sec/.cache/efts",
    )
    ap.add_argument("--wait", type=float, default=0.3, help="seconds between EDGAR queries")
    args = ap.parse_args()

    payload = json.loads(COMPANIES_PATH.read_text())
    companies = payload["companies"]
    layer_names = {layer["id"]: layer["name"] for layer in payload.get("layers", [])}
    print(f"universe: {len(companies)} companies")

    companies = resolve_companies(companies)
    print(f"resolved {len(companies)} tickers to CIK")

    graph = build(
        companies,
        k_industry=args.industry_neighbors,
        include_crossref=not args.offline and not args.no_crossref,
        include_cohold=not args.offline and not args.no_cohold,
        wait=args.wait,
        cohold_min_shared=args.cohold_min_shared,
        cohold_neighbors=args.cohold_neighbors,
        refresh_cache=args.refresh_cache,
        layer_names=layer_names,
    )
    json_path = write_json_artifact(GRAPH_PATH, graph)
    types = Counter(link["type"] for link in graph["links"])
    total = f"{len(graph['nodes'])} nodes, {len(graph['links'])} links, {dict(types)}"
    print(f"wrote {json_path} — {total}")


if __name__ == "__main__":
    main()
