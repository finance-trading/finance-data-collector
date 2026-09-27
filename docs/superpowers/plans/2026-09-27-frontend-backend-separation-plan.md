# Frontend and Backend Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a Vite multi-page TypeScript frontend and a FastAPI-owned paginated AI company catalog while preserving all four current URLs on port 8000.

**Architecture:** Move canonical and generated data to backend-owned `data/`, expose it through read-only APIs, and build the four browser pages from `frontend/`. During migration, first move the existing pages into Vite without behavior changes, then replace each page with focused TypeScript modules; FastAPI mounts only `frontend/dist` after its API routes.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL/SQLite tests, Node 22, npm, Vite 7, TypeScript 5.9, Vitest 3, jsdom, D3 7, 3d-force-graph 1.80, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-26-frontend-backend-separation-design.md`

## Global Constraints

- Keep `/`, `/company.html?ticker=...`, `/graph.html`, and `/layers.html` compatible.
- Port 8000 must serve the built index page after `npm run build`.
- The frontend sends GET requests only and treats API content as untrusted text.
- Preserve explicit `parsed`, `failed`, `unavailable`, and `not_ingested` states.
- Default directory page size is 25; accepted sizes are 25, 50, and 100.
- The supported minimum viewport width is 320 pixels.
- Direct `file://` viewing is removed.
- Do not move, delete, stage, or commit `web/_dbg_index.html` or `download_all_sec.sh`.
- Every Git command and commit is delegated to a `routine_ops` agent.
- Each task follows red-green-refactor and ends in a scoped commit.

---

## Planned file ownership

- `data/ai_companies.json`: canonical ordered AI universe.
- `data/generated/*.json`: Python-generated visualization artifacts.
- `src/fdc/data_files.py`: repository data paths and JSON artifact I/O.
- `src/fdc/catalog.py`: catalog validation, database merge, filtering, sorting, and pagination.
- `src/fdc/api.py`: HTTP contracts and final frontend mount.
- `frontend/src/api/*`: shared browser request and response contracts.
- `frontend/src/components/*`: DOM-only shared UI units.
- `frontend/src/pages/*`: one entry module per page.
- `frontend/src/styles/*`: shared tokens plus page-specific layout.
- `tests/`: Python contracts and real-browser acceptance.
- `frontend/tests/`: TypeScript behavior tests.

### Task 1: Move canonical and generated data behind backend-owned paths

**Files:**
- Create: `src/fdc/data_files.py`
- Move: `web/data/companies.json` → `data/ai_companies.json`
- Move: `web/data/graph.json` → `data/generated/graph.json`
- Move: `web/data/layers.json` → `data/generated/layers.json`
- Delete: `web/data/graph.js`
- Delete: `web/data/layers.js`
- Delete: `src/fdc/web_data.py`
- Modify: `src/fdc/graph.py`
- Modify: `src/fdc/ai_layers.py`
- Modify: `tests/unit/test_graph.py`
- Modify: `tests/unit/test_ai_layers.py`
- Replace: `tests/unit/test_web_data.py` with `tests/unit/test_data_files.py`

**Interfaces:**
- Produces: `CATALOG_PATH`, `GENERATED_DATA_DIR`, `GRAPH_PATH`, `LAYERS_PATH`.
- Produces: `write_json_artifact(path: Path, payload: dict[str, Any]) -> Path`.
- Consumed by: catalog and visualization API tasks.

- [ ] **Step 1: Write failing path and writer tests**

```python
from fdc.data_files import (
    CATALOG_PATH,
    GRAPH_PATH,
    LAYERS_PATH,
    write_json_artifact,
)
from fdc.sec_storage import PROJECT_ROOT


def test_data_paths_are_backend_owned():
    assert CATALOG_PATH == PROJECT_ROOT / "data" / "ai_companies.json"
    assert GRAPH_PATH == PROJECT_ROOT / "data" / "generated" / "graph.json"
    assert LAYERS_PATH == PROJECT_ROOT / "data" / "generated" / "layers.json"
    assert "web" not in GRAPH_PATH.parts


def test_write_json_artifact_writes_only_json(tmp_path):
    output = write_json_artifact(tmp_path / "generated" / "graph.json", {"nodes": []})
    assert json.loads(output.read_text()) == {"nodes": []}
    assert not output.with_suffix(".js").exists()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q tests/unit/test_data_files.py tests/unit/test_ai_layers.py tests/unit/test_graph.py`

Expected: collection fails because `fdc.data_files` does not exist or old `web/data` paths are returned.

- [ ] **Step 3: Add the backend data-path module**

```python
"""Canonical and generated repository data paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fdc.sec_storage import PROJECT_ROOT

DATA_ROOT = PROJECT_ROOT / "data"
CATALOG_PATH = DATA_ROOT / "ai_companies.json"
GENERATED_DATA_DIR = DATA_ROOT / "generated"
GRAPH_PATH = GENERATED_DATA_DIR / "graph.json"
LAYERS_PATH = GENERATED_DATA_DIR / "layers.json"


def write_json_artifact(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    return path
```

- [ ] **Step 4: Move the JSON files and update both generators**

Use patch move operations for the three JSON files. Replace `WEB_DIR`, the old path constants, and `write_data` calls with imports from `fdc.data_files`. Generator completion messages must print only the JSON path:

```python
from fdc.data_files import CATALOG_PATH, GRAPH_PATH, LAYERS_PATH, write_json_artifact

# graph.py
payload = json.loads(CATALOG_PATH.read_text())
json_path = write_json_artifact(GRAPH_PATH, graph)
print(f"wrote {json_path}")

# ai_layers.py
def write_tree(path: Path, payload: dict) -> Path:
    return write_json_artifact(path, payload)
```

Update module docstrings, CLI help, and tests to refer to `data/ai_companies.json` and `data/generated/*.json`. Remove all JS-shim assertions and delete the obsolete shim writer.

- [ ] **Step 5: Run focused tests and generator smoke checks**

Run:

```bash
uv run pytest -q tests/unit/test_data_files.py tests/unit/test_ai_layers.py tests/unit/test_graph.py
uv run python -m fdc.ai_layers --tree
uv run python -m fdc.ai_layers --mermaid
```

Expected: tests pass; both commands read `data/ai_companies.json`; no `.js` artifact is created.

- [ ] **Step 6: Delegate the scoped commit**

Delegate exact staging of the Task 1 paths to `routine_ops` with commit message `refactor: separate generated data`.

### Task 2: Add the catalog service and visualization read APIs

**Files:**
- Create: `src/fdc/catalog.py`
- Create: `tests/unit/test_catalog.py`
- Modify: `src/fdc/api.py`
- Modify: `tests/integration/test_api_filings.py`
- Modify: `tests/conftest.py`
- Modify: `web/graph.html`
- Modify: `web/layers.html`

**Interfaces:**
- Consumes: `CATALOG_PATH`, `GRAPH_PATH`, `LAYERS_PATH` from Task 1.
- Produces: `CompanyDirectoryItem`, `CompanyDirectoryView`, `CatalogLayerListView`.
- Produces: `list_companies(query, layer, segment, ingestion_status, limit, offset, session_factory=SessionLocal)`.
- Produces: `list_layers()` and `read_visualization(name)`.
- Produces HTTP: `/api/v1/catalog/layers`, `/api/v1/visualizations/graph`, `/api/v1/visualizations/layers`.
- Defers switching `/api/v1/companies` to Task 4 so the current homepage remains compatible during migration.

- [ ] **Step 1: Write failing catalog validation and merge tests**

```python
import json

import pytest


def write_catalog_fixture(tmp_path):
    path = tmp_path / "ai_companies.json"
    path.write_text(json.dumps({
        "layers": [
            {"id": "power", "name": "Power", "name_en": "Power", "segments": ["Grid"]},
            {
                "id": "silicon", "name": "Silicon", "name_en": "Silicon",
                "segments": ["Compute", "Memory"],
            },
        ],
        "companies": [
            {
                "ticker": "VRT", "name": "Vertiv", "sector": "Industrials",
                "industry": "Electrical Equipment", "layer": "power",
                "segment": "Grid", "description": "Power infrastructure",
            },
            {
                "ticker": "NVDA", "name": "NVIDIA", "sector": "Technology",
                "industry": "Semiconductors", "layer": "silicon",
                "segment": "Compute", "description": "Accelerated compute",
            },
            {
                "ticker": "AMD", "name": "AMD", "sector": "Technology",
                "industry": "Semiconductors", "layer": "silicon",
                "segment": "Compute", "description": "Compute silicon",
            },
        ],
    }))
    return path


@pytest.fixture
def catalog_path(tmp_path):
    return write_catalog_fixture(tmp_path)


def test_catalog_preserves_declared_layer_and_segment_order(tmp_path):
    path = write_catalog_fixture(tmp_path)
    catalog = load_catalog(path)
    assert [layer.id for layer in catalog.layers] == ["power", "silicon"]
    assert [company.ticker for company in catalog.companies] == ["VRT", "NVDA", "AMD"]


def test_directory_includes_catalog_only_company(session_factory, catalog_path):
    result = list_companies(
        query="VRT",
        layer=None,
        segment=None,
        ingestion_status=None,
        limit=25,
        offset=0,
        catalog_path=catalog_path,
        session_factory=session_factory,
    )
    assert result.total == 1
    assert result.companies[0].ingestion_status == "not_ingested"
    assert result.companies[0].filing_count == 0
    assert result.companies[0].research_available is False
```

Add cases for parsed, failed, unavailable, duplicate issuer selection, name search, combined filters, default catalog order, and offset beyond total.

- [ ] **Step 2: Run catalog tests and verify RED**

Run: `uv run pytest -q tests/unit/test_catalog.py`

Expected: FAIL because `fdc.catalog` and its models do not exist.

- [ ] **Step 3: Implement typed catalog loading and pure filtering**

```python
class CatalogCompany(BaseModel):
    ticker: str
    name: str
    sector: str
    industry: str
    layer: str
    segment: str
    description: str
    also_in: list[str] = Field(default_factory=list)


class CompanyDirectoryItem(CatalogCompany):
    layer_name: str
    cik: str | None = None
    latest_filing_date: date | None = None
    latest_filing_status: str | None = None
    ingestion_status: Literal["parsed", "failed", "unavailable", "not_ingested"]
    filing_count: int
    research_available: bool


class CompanyDirectoryView(BaseModel):
    query: str | None
    layer: str | None
    segment: str | None
    ingestion_status: str | None
    limit: int
    offset: int
    total: int
    companies: list[CompanyDirectoryItem]
```

`load_catalog` validates unique uppercase tickers, declared layers, declared segments, and non-empty required fields. `list_companies` performs one joined database read, reduces rows to canonical ticker summaries, merges them into catalog order, filters, calculates `total`, and only then slices `[offset:offset + limit]`.

- [ ] **Step 4: Write failing API tests for metadata and visualization errors**

```python
def test_catalog_layers_preserve_declared_counts(client):
    response = client.get("/api/v1/catalog/layers")
    assert response.status_code == 200
    assert response.json()["total_companies"] == 211
    assert response.json()["layers"][0]["id"] == "power"


def test_missing_visualization_is_explicit(client, monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "GRAPH_PATH", tmp_path / "missing.json")
    response = client.get("/api/v1/visualizations/graph")
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "unavailable"
```

- [ ] **Step 5: Register the read endpoints and update legacy viewers**

```python
@app.get("/api/v1/catalog/layers", response_model=CatalogLayerListView)
def catalog_layers() -> CatalogLayerListView:
    return _read(catalog.list_layers)


@app.get("/api/v1/visualizations/{name}")
def visualization(name: Literal["graph", "layers"]) -> dict[str, Any]:
    return _read(lambda: catalog.read_visualization(name))
```

Change the two legacy page loaders to a single fetch with explicit failure:

```javascript
async function loadData(name) {
  const response = await fetch(`/api/v1/visualizations/${name}`);
  if (!response.ok) throw new Error(`${name} request returned ${response.status}`);
  return response.json();
}
```

- [ ] **Step 6: Run backend and browser-compatibility tests**

Run:

```bash
uv run pytest -q tests/unit/test_catalog.py tests/integration/test_api_filings.py tests/unit/test_web_index.py
uv run ruff check src tests
```

Expected: all pass; the existing directory endpoint is unchanged; legacy graph and layers load through the new APIs.

- [ ] **Step 7: Delegate the scoped commit**

Delegate Task 2 paths to `routine_ops` with commit message `feat: add AI catalog read APIs`.

### Task 3: Establish the Vite multi-page boundary without changing page behavior

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/env.d.ts`
- Move: tracked `web/index.html`, `web/company.html`, `web/graph.html`, `web/layers.html` → `frontend/*.html`
- Move: `web/index.js`, `web/company.js` → `frontend/src/legacy/*.js`
- Move: `web/data/index.css`, `web/data/company.css` → `frontend/src/styles/*.css`
- Modify: four moved HTML entry files
- Modify: `src/fdc/api.py`
- Modify: `.gitignore`
- Modify: `tests/unit/test_web_index.py`
- Modify: `tests/acceptance/test_company_page.py`
- Modify: `tests/acceptance/conftest.py`

**Interfaces:**
- Produces npm scripts: `dev`, `build`, `typecheck`, `test`.
- Produces Vite entries: `index.html`, `company.html`, `graph.html`, `layers.html`.
- Produces backend setting/path `FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"`.
- Keeps all current browser behavior while later tasks replace legacy JavaScript.

- [ ] **Step 1: Write failing production-mount and source-location tests**

```python
import httpx

FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def test_frontend_has_all_vite_page_entries():
    assert {path.name for path in FRONTEND_ROOT.glob("*.html")} == {
        "index.html", "company.html", "graph.html", "layers.html"
    }


def test_read_app_serves_built_index_on_root(live_server):
    response = httpx.get(f"{live_server}/")
    assert response.status_code == 200
    assert "Research starts with the filing." in response.text
```

Update all static source assertions from `web/` to `frontend/` and make the acceptance fixture build the frontend before uvicorn starts.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run pytest -q tests/unit/test_web_index.py tests/acceptance/test_company_page.py -k 'mounts or serves or research_home'`

Expected: FAIL because `frontend/` and its production build do not exist.

- [ ] **Step 3: Create the Vite package and multi-page config**

```json
{
  "name": "finance-data-collector-web",
  "private": true,
  "type": "module",
  "engines": {"node": ">=22"},
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  },
  "dependencies": {
    "3d-force-graph": "1.80.0",
    "d3": "7.9.0"
  },
  "devDependencies": {
    "@types/d3": "7.4.3",
    "@types/node": "22.18.6",
    "jsdom": "26.1.0",
    "typescript": "5.9.2",
    "vite": "7.1.7",
    "vitest": "3.2.4"
  }
}
```

```typescript
// frontend/vite.config.ts
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        index: resolve(root, "index.html"),
        company: resolve(root, "company.html"),
        graph: resolve(root, "graph.html"),
        layers: resolve(root, "layers.html"),
      },
    },
  },
  server: {proxy: {"/api": "http://127.0.0.1:8000"}},
  test: {environment: "jsdom", include: ["tests/**/*.test.ts"]},
});
```

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "types": ["node", "vitest/globals"]
  },
  "include": ["src", "tests", "vite.config.ts"]
}
```

`frontend/src/env.d.ts` contains only `/// <reference types="vite/client" />`.

- [ ] **Step 4: Move the four pages into Vite and update asset imports**

Use patch move operations for tracked files only. Leave `web/_dbg_index.html` untouched. Replace legacy script/style references with Vite source paths:

```html
<link rel="stylesheet" href="/src/styles/index.css">
<script type="module" src="/src/legacy/index.js"></script>
```

Graph and layers retain their inline module bodies temporarily, but import npm packages by bare specifier (`3d-force-graph` and `d3`) rather than CDN URLs.

- [ ] **Step 5: Mount the build after API routes**

```python
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount(
    "/",
    StaticFiles(directory=FRONTEND_DIST, html=True, check_dir=False),
    name="frontend",
)
```

Add `node_modules/` and `frontend/dist/` to `.gitignore`. In the acceptance fixture, run `npm ci` only when `node_modules` is absent, then always run `npm run build` before starting uvicorn.

- [ ] **Step 6: Install, build, and run focused tests**

Run:

```bash
cd frontend && npm install && npm run build
cd .. && uv run pytest -q tests/unit/test_web_index.py tests/acceptance/test_company_page.py
```

Expected: Vite emits all four HTML entries; port-8000 acceptance remains behaviorally unchanged.

- [ ] **Step 7: Delegate the scoped commit**

Delegate only Task 3 files, including `package-lock.json`, to `routine_ops` with commit message `refactor: separate web frontend`.

### Task 4: Deliver the paginated AI directory in TypeScript

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/data-state.ts`
- Create: `frontend/src/components/pagination.ts`
- Create: `frontend/src/pages/directory.ts`
- Create: `frontend/tests/directory.test.ts`
- Modify: `frontend/index.html`
- Modify: `frontend/src/styles/index.css`
- Delete: `frontend/src/legacy/index.js`
- Modify: `src/fdc/api.py`
- Modify: `tests/integration/test_api_filings.py`
- Modify: `tests/acceptance/test_company_page.py`

**Interfaces:**
- Consumes: `catalog.list_companies` and `/api/v1/catalog/layers` from Task 2.
- Produces: `apiGet<T>(path, params, signal) -> Promise<T>`.
- Produces: `readDirectoryState(search: URLSearchParams) -> DirectoryState`.
- Produces: `writeDirectoryState(state: DirectoryState) -> URLSearchParams`.
- Produces: `renderPagination(model: PaginationModel, onPage: (page: number) => void)`.
- Switches `/api/v1/companies` to the catalog-backed contract.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_company_directory_paginates_the_complete_catalog(client):
    first = client.get("/api/v1/companies?limit=25&offset=0")
    last = client.get("/api/v1/companies?limit=25&offset=200")
    assert first.status_code == 200
    assert first.json()["total"] == 211
    assert len(first.json()["companies"]) == 25
    assert len(last.json()["companies"]) == 11


def test_company_directory_combines_layer_and_status_filters(client):
    response = client.get(
        "/api/v1/companies?layer=silicon&ingestion_status=not_ingested&limit=100"
    )
    assert response.status_code == 200
    assert all(item["layer"] == "silicon" for item in response.json()["companies"])
    assert all(
        item["ingestion_status"] == "not_ingested"
        for item in response.json()["companies"]
    )
```

- [ ] **Step 2: Run the API tests and verify RED**

Run: `uv run pytest -q tests/integration/test_api_filings.py -k company_directory`

Expected: FAIL because the current endpoint contains only persisted issuers and lacks filters.

- [ ] **Step 3: Switch the route to the catalog service**

```python
@app.get("/api/v1/companies", response_model=CompanyDirectoryView)
def companies(
    query: str | None = None,
    layer: str | None = None,
    segment: str | None = None,
    ingestion_status: Annotated[IngestionStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyDirectoryView:
    return _read(
        lambda: catalog.list_companies(
            query, layer, segment, ingestion_status, limit, offset
        )
    )
```

Retain `GET /api/v1/companies/{ticker}` and its existing database-only behavior.

- [ ] **Step 4: Write failing TypeScript tests for URL state and pagination**

```typescript
it("round-trips directory filters through the URL", () => {
  const state = readDirectoryState(new URLSearchParams(
    "query=nvda&layer=silicon&status=parsed&page=2&pageSize=50",
  ));
  expect(state).toEqual({
    query: "nvda", layer: "silicon", segment: "", status: "parsed",
    page: 2, pageSize: 50,
  });
  expect(writeDirectoryState(state).toString()).toContain("page=2");
});

it("disables research navigation for catalog-only companies", () => {
  document.body.innerHTML = '<tbody id="company-directory"></tbody>';
  renderCompanies([catalogOnlyCompany]);
  expect(document.querySelector("a[href*='company.html']")).toBeNull();
  expect(document.body.textContent).toContain("Not ingested");
});
```

- [ ] **Step 5: Implement the shared API client and directory state**

```typescript
export async function apiGet<T>(
  path: string,
  params: URLSearchParams = new URLSearchParams(),
  signal?: AbortSignal,
): Promise<T> {
  const query = params.size ? `?${params.toString()}` : "";
  const response = await fetch(`${path}${query}`, {signal});
  if (!response.ok) throw new ApiError(response.status, await response.json());
  return response.json() as Promise<T>;
}

export interface DirectoryState {
  query: string;
  layer: string;
  segment: string;
  status: "" | IngestionStatus;
  page: number;
  pageSize: 25 | 50 | 100;
}
```

`directory.ts` owns one current `AbortController`, updates URL state with
`history.replaceState`, resets `page` on filter change, calculates
`offset = (page - 1) * pageSize`, and ignores `AbortError` without logging.

- [ ] **Step 6: Replace the directory markup and render all explicit states**

Add labeled search, layer, segment, status, and page-size controls; directory
table/card rows; `<nav id="directory-pagination" aria-label="Company pages">`;
and a retry button inside the state region. DOM rendering must use
`textContent` and `setAttribute` for catalog values.

```typescript
const research = company.research_available
  ? link("Open research", `company.html?ticker=${encodeURIComponent(company.ticker)}`)
  : text("Not ingested", "availability availability-missing");
```

- [ ] **Step 7: Run frontend, API, and browser tests**

Run:

```bash
cd frontend && npm test && npm run build
cd .. && uv run pytest -q tests/integration/test_api_filings.py tests/acceptance/test_company_page.py -k 'company_directory or research_home'
```

Expected: 211 total companies, 25 first-page rows, working URL restoration, no 404 action for catalog-only rows, and no console errors.

- [ ] **Step 8: Delegate the scoped commit**

Delegate Task 4 paths to `routine_ops` with commit message `feat: paginate AI company directory`.

### Task 5: Migrate the company research workspace to shared TypeScript

**Files:**
- Create: `frontend/src/pages/company.ts`
- Create: `frontend/src/components/site-shell.ts`
- Create: `frontend/tests/company.test.ts`
- Modify: `frontend/company.html`
- Modify: `frontend/src/styles/company.css`
- Modify: `frontend/src/api/types.ts`
- Delete: `frontend/src/legacy/company.js`
- Modify: `tests/acceptance/test_company_page.py`

**Interfaces:**
- Consumes: `apiGet`, filing/fact/statement/section/table/evidence endpoints.
- Produces: `loadCompany(ticker, signal)`, `loadFiling(accession, signal)`, and
  `selectEvidence(accession, evidenceId, selectionToken)`.
- Preserves the existing query-string ticker URL and stale-response guards.

- [ ] **Step 1: Write failing TypeScript behavior tests**

```typescript
it("normalizes the ticker from the query string", () => {
  expect(readTicker(new URL("http://test/company.html?ticker=nvda"))).toBe("NVDA");
});

it("does not let stale evidence replace a newer filing", async () => {
  const state = createCompanyState();
  const stale = state.beginEvidence("old-accession");
  state.selectFiling("new-accession");
  expect(state.acceptEvidence(stale, evidenceFixture)).toBe(false);
});

it("maps API states to explicit labels", () => {
  expect(companyStatusLabel(404)).toBe("Not found");
  expect(companyStatusLabel(409)).toBe("Unavailable");
  expect(companyStatusLabel(422)).toBe("Parse failed");
});
```

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `cd frontend && npm test -- company.test.ts`

Expected: FAIL because `pages/company.ts` is missing.

- [ ] **Step 3: Define the filing API types and migrate the state machine**

```typescript
export interface FilingSummary {
  accession: string;
  form: string;
  filing_date: string | null;
  report_date: string | null;
  status: "success" | "failed" | "unavailable";
  parser_version: string | null;
}

interface RequestToken {
  accession: string;
  sequence: number;
}

export function createCompanyState() {
  let accession = "";
  let sequence = 0;
  return {
    selectFiling(next: string) { accession = next; sequence += 1; },
    beginEvidence(selected: string): RequestToken {
      return {accession: selected, sequence};
    },
    acceptEvidence(token: RequestToken): boolean {
      return token.accession === accession && token.sequence === sequence;
    },
  };
}
```

Move the current statement tabs, filing selection, fact rendering, disclosure
rendering, and evidence rendering into named functions. Keep raw reported
values and periods unchanged; do not add client-side calculations.

- [ ] **Step 4: Add the shared site shell and home navigation**

`site-shell.ts` renders the common product mark and links to Research, Company
graph, and AI layers. Add a Research link to the company workspace without
changing the three-column filing layout.

```typescript
export function markCurrentNav(pathname: string): void {
  document.querySelectorAll<HTMLAnchorElement>("[data-nav]").forEach(anchor => {
    const current = new URL(anchor.href).pathname === pathname;
    if (current) anchor.setAttribute("aria-current", "page");
    else anchor.removeAttribute("aria-current");
  });
}
```

- [ ] **Step 5: Update browser acceptance for the TypeScript entry**

Keep all existing company assertions and add navigation back to the directory,
keyboard tab selection, and console-error capture. The stale-evidence test must
still reject a delayed failure after changing filings.

- [ ] **Step 6: Run the focused frontend and acceptance suites**

Run:

```bash
cd frontend && npm test -- company.test.ts && npm run build
cd .. && uv run pytest -q tests/acceptance/test_company_page.py -k 'company_page or stale_evidence or narrow_statement'
```

Expected: all pass with the same persisted MSFT/NVDA behavior and explicit
failure states.

- [ ] **Step 7: Delegate the scoped commit**

Delegate Task 5 paths to `routine_ops` with commit message `refactor: migrate company research frontend`.

### Task 6: Migrate the 3D company graph to a typed Vite module

**Files:**
- Create: `frontend/src/pages/graph.ts`
- Create: `frontend/src/styles/graph.css`
- Create: `frontend/tests/graph.test.ts`
- Modify: `frontend/graph.html`
- Modify: `frontend/src/api/types.ts`
- Modify: `tests/unit/test_web_index.py`
- Modify: `tests/acceptance/test_company_page.py`

**Interfaces:**
- Consumes: `/api/v1/visualizations/graph` and npm `3d-force-graph`.
- Produces: `normalizeGraph(payload)`, `degreeByTicker(graph)`, and
  `mountGraph(container, graph)`.
- Preserves ticker node identity, node/link filtering, zoom-to-fit, and the
  `window.__graph` browser-QA hook.

- [ ] **Step 1: Write failing graph normalization tests**

```typescript
it("normalizes numeric link endpoints to ticker identity", () => {
  const graph = normalizeGraph({
    nodes: [{id: 1045810, ticker: "NVDA", name: "NVIDIA"}],
    links: [{source: 1045810, target: 1045810, type: "industry", weight: 1}],
  });
  expect(graph.links[0]).toMatchObject({source: "NVDA", target: "NVDA"});
});

it("counts degree by ticker rather than CIK", () => {
  expect(degreeByTicker(twoTickerGraph)).toEqual({GOOG: 1, GOOGL: 1});
});
```

- [ ] **Step 2: Run graph tests and verify RED**

Run: `cd frontend && npm test -- graph.test.ts`

Expected: FAIL because the typed graph module does not exist.

- [ ] **Step 3: Extract graph types and pure normalization helpers**

```typescript
export interface GraphNode {
  id: number | string;
  ticker: string;
  name: string;
  sector?: string;
  industry?: string;
  layer?: string;
  layer_name?: string;
  segment?: string;
  description?: string;
  edgar?: string;
}

export function normalizeGraph(payload: GraphPayload): GraphPayload {
  const tickerById = new Map(payload.nodes.map(node => [String(node.id), node.ticker]));
  return {
    ...payload,
    links: payload.links.map(link => ({
      ...link,
      source: endpointTicker(link.source, tickerById),
      target: endpointTicker(link.target, tickerById),
    })),
  };
}
```

- [ ] **Step 4: Move the runtime from inline HTML into `graph.ts`**

Import `ThreeForceGraph` from npm, fetch through `apiGet`, and build detail
panels with DOM APIs. Preserve these runtime invariants:

```typescript
const graph = ThreeForceGraph()(container)
  .graphData(data)
  .nodeId("ticker")
  .nodeLabel(node => `${node.name} (${node.ticker})`)
  .onEngineStop(() => graph.zoomToFit(800, 80));

declare global { interface Window { __graph?: unknown } }
window.__graph = graph;
```

Render a visible retry state if the API is unavailable. Remove every generated-
data `innerHTML` assignment from the migrated handler.

- [ ] **Step 5: Add real browser graph assertions**

The acceptance test waits for `window.__graph`, asserts one canvas, asserts
211 graph nodes, toggles a link filter, and clicks or programmatically selects
two distinct nodes to verify distinct ticker names. Capture runtime and console
errors.

- [ ] **Step 6: Run graph unit, build, and browser checks**

Run:

```bash
cd frontend && npm test -- graph.test.ts && npm run build
cd .. && uv run pytest -q tests/unit/test_web_index.py tests/acceptance/test_company_page.py -k graph
```

Expected: tests pass and the graph renders one non-empty canvas from the API.

- [ ] **Step 7: Delegate the scoped commit**

Delegate Task 6 paths to `routine_ops` with commit message `refactor: migrate company graph frontend`.

### Task 7: Migrate the AI layers viewer to a typed Vite module

**Files:**
- Create: `frontend/src/pages/layers.ts`
- Create: `frontend/src/styles/layers.css`
- Create: `frontend/tests/layers.test.ts`
- Modify: `frontend/layers.html`
- Modify: `frontend/src/api/types.ts`
- Modify: `tests/unit/test_web_index.py`
- Modify: `tests/acceptance/test_company_page.py`

**Interfaces:**
- Consumes: `/api/v1/visualizations/layers` and npm `d3`.
- Produces: `flattenLayers(payload)`, `toggleLayer(id)`, `toggleSegment(id)`,
  `renderColumns`, `renderTree`, and `renderMermaid`.
- Preserves two-level collapse, search, cross-layer toggles, framing, and modes.

- [ ] **Step 1: Write failing hierarchy and collapse tests**

```typescript
it("flattens root to layer, segment, and company records", () => {
  const result = flattenLayers(layerFixture);
  expect(result.layers).toHaveLength(1);
  expect(result.segments[0].layerId).toBe("silicon");
  expect(result.companies[0].ticker).toBe("NVDA");
});

it("collapsing one segment does not collapse its sibling", () => {
  const state = createCollapseState();
  state.toggleSegment("silicon/compute");
  expect(state.isSegmentCollapsed("silicon/compute")).toBe(true);
  expect(state.isSegmentCollapsed("silicon/memory")).toBe(false);
});
```

- [ ] **Step 2: Run layers tests and verify RED**

Run: `cd frontend && npm test -- layers.test.ts`

Expected: FAIL because `pages/layers.ts` does not exist.

- [ ] **Step 3: Extract typed hierarchy state and render functions**

```typescript
export function createCollapseState() {
  const layers = new Set<string>();
  const segments = new Set<string>();
  return {
    toggleLayer(id: string) { layers.has(id) ? layers.delete(id) : layers.add(id); },
    toggleSegment(id: string) {
      segments.has(id) ? segments.delete(id) : segments.add(id);
    },
    isLayerCollapsed: (id: string) => layers.has(id),
    isSegmentCollapsed: (id: string) => segments.has(id),
  };
}
```

Move columns, tree, Mermaid, zoom/fit, legend, search, card, and resize behavior
out of inline HTML. Fetch via `apiGet`; assign all company-provided text with
`.text()` or `textContent`, never HTML interpolation.

- [ ] **Step 4: Preserve framing and responsive controls**

Keep the top-aligned initial column framing, the existing fit calculation, and
independent layer/segment collapse. At narrow widths the toolbar wraps or
scrolls without covering the visualization. Add a visible loading/error region
above the SVG and a retry action.

- [ ] **Step 5: Add browser interaction tests**

The acceptance test switches among columns, tree, and Mermaid; collapses one
layer and one segment; searches `NVDA`; opens its card; clears the search; and
asserts no console errors at desktop and 390-pixel widths.

- [ ] **Step 6: Run layers unit, build, and browser checks**

Run:

```bash
cd frontend && npm test -- layers.test.ts && npm run build
cd .. && uv run pytest -q tests/unit/test_web_index.py tests/acceptance/test_company_page.py -k layers
```

Expected: all three modes and both collapse levels work from the API payload.

- [ ] **Step 7: Delegate the scoped commit**

Delegate Task 7 paths to `routine_ops` with commit message `refactor: migrate AI layers frontend`.

### Task 8: Remove migration residue, document workflows, and validate the complete system

**Files:**
- Delete: `frontend/src/legacy/` after it is empty
- Modify: `README.md`
- Modify: `docs/runbook.md`
- Modify: `tests/acceptance/conftest.py`
- Modify: any test still referring to tracked `web/` production assets

**Interfaces:**
- Consumes all earlier tasks.
- Produces documented development and production-style commands.
- Produces the final invariant: no tracked production code or generated data
  lives under `web/`; the unrelated untracked debug file remains untouched.

- [ ] **Step 1: Add a failing repository-boundary test**

```python
from pathlib import Path


def test_python_and_frontend_sources_do_not_reference_legacy_web_data():
    project_root = Path(__file__).resolve().parents[2]
    src_root = project_root / "src"
    frontend_root = project_root / "frontend"
    offenders = []
    for path in [*src_root.rglob("*.py"), *frontend_root.rglob("*.ts")]:
        text = path.read_text()
        if "web/data" in text or "__FDC_DATA__" in text:
            offenders.append(str(path.relative_to(project_root)))
    assert offenders == []
```

- [ ] **Step 2: Run the boundary test and remove remaining references**

Run: `uv run pytest -q tests/unit/test_web_index.py -k legacy_web_data`

Expected before cleanup: FAIL listing any legacy source. Remove only tracked
migration residue; leave `web/_dbg_index.html` and `download_all_sec.sh`
untouched.

- [ ] **Step 3: Document exact workflows**

README and runbook must include these commands:

```bash
# API plus Vite hot reload
FDC_DATABASE_URL='postgresql+psycopg://fdc:fdc@localhost:5432/fdc' \
  uv run uvicorn fdc.api:app --reload --host 127.0.0.1 --port 8000
cd frontend && npm ci && npm run dev

# Production-style single origin at http://127.0.0.1:8000/
cd frontend && npm ci && npm run build
cd .. && uv run uvicorn fdc.api:app --host 127.0.0.1 --port 8000

# Regenerate visualization payloads
uv run python -m fdc.graph
uv run python -m fdc.ai_layers --enrich-graph
```

Explain that `file://` is unsupported, Vite proxies API calls in development,
and built assets are not committed.

- [ ] **Step 4: Run every automated gate**

Run:

```bash
cd frontend && npm ci && npm test && npm run typecheck && npm run build
cd .. && uv run pytest -q
uv run ruff check src tests alembic
uv run python -m compileall -q src tests alembic
```

Expected: all frontend and Python tests pass with no warnings or unexpected
skips beyond environment-gated tests.

- [ ] **Step 5: Restart the real PostgreSQL-backed service**

Stop the existing uvicorn session and start the built application with the
PostgreSQL URL and SEC user agent. Verify with read-only requests:

```bash
curl -fsS http://127.0.0.1:8000/ | rg "Research starts with the filing"
curl -fsS 'http://127.0.0.1:8000/api/v1/companies?limit=25&offset=0' \
  | jq '{total, page_count: (.companies | length)}'
curl -fsS http://127.0.0.1:8000/api/v1/companies/NVDA \
  | jq '{ticker, filing_count, latest_filing_status}'
```

Expected: root is the Vite index, directory total is 211 with 25 first-page
rows, and NVDA remains database-backed.

- [ ] **Step 6: Perform real browser QA**

At 1280×800 and 390×844, verify directory search/filter/pagination/URL restore,
catalog-only non-action, NVDA navigation, filing selection, evidence, graph
render/filter/node identity, layer modes/collapse/search, focus visibility,
page overflow, failed-request states, console errors, and network errors.

- [ ] **Step 7: Delegate the final scoped commit**

Delegate Task 8 documentation and cleanup paths to `routine_ops` with commit
message `docs: finalize separated web workflow`. Ask the agent to verify final
status and preserve unrelated untracked files.

## Execution order and checkpoints

Execute Tasks 1–8 in order. After each task: run its focused gates, delegate a
scoped commit, inspect the returned commit hash/status, and only then continue.
If a task reveals a contract mismatch, update this plan and the design spec in
the same task before implementation continues.
