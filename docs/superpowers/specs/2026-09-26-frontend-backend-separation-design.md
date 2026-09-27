# Frontend and Backend Separation for the SEC Research Web

## Status

Design draft for user review. Implementation has not started.

## Problem

The repository currently mixes browser assets, generated visualization data,
and backend-owned company catalog data under `web/`. FastAPI serves that
directory directly, while Python generators also read and write files inside
it. The new research homepage only lists issuers already present in the
database, so it cannot display the complete 211-company AI universe or provide
useful pagination and catalog filters.

The project needs independently organized frontend and backend source trees
without losing the single local entry point at `http://127.0.0.1:8000/`.

## Goals

1. Move all four web experiences—directory, company research, company graph,
   and AI layers—into one Vite multi-page TypeScript application.
2. Keep FastAPI, SEC parsing, persistence, catalog merging, and generated-data
   production in `src/fdc/`.
3. Make the complete curated AI company universe available through a paginated
   read API, including companies that have not been ingested.
4. Preserve `/`, `/company.html?ticker=...`, `/graph.html`, and `/layers.html`.
5. Keep the normal production-style entry point on port 8000 while supporting
   a separate Vite development server.
6. Preserve explicit parsed, failed, unavailable, and not-ingested states.
7. Remove browser ownership of canonical company and visualization data.

## Non-goals

- Introducing React or another component framework.
- Adding write APIs, download controls, parser controls, authentication, or
  user accounts.
- Changing SEC parsing semantics or the filing evidence model.
- Adding market prices, analyst estimates, ratings, or investment advice.
- Preserving direct `file://` access to HTML pages.
- Deploying the frontend and backend to separate public domains in this phase.

## Chosen approach

Use Vite as a multi-page application with vanilla TypeScript. Each current
page remains a separate HTML entry, but all pages share API, shell, state,
formatting, and styling modules.

This is preferred over a client-routed single-page application because it
preserves the current URLs and keeps the graph and layer viewers isolated from
the research workspace. It is preferred over separate public origins because
the user requires port 8000 to open the index page directly and the project
does not need CORS or two deployment targets yet.

## Repository layout

```text
data/
  ai_companies.json
  generated/
    graph.json
    layers.json

frontend/
  index.html
  company.html
  graph.html
  layers.html
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  src/
    api/
      client.ts
      types.ts
    components/
      data-state.ts
      pagination.ts
      site-shell.ts
    pages/
      company.ts
      directory.ts
      graph.ts
      layers.ts
    styles/
      tokens.css
      directory.css
      company.css
      visualizations.css
  tests/

src/fdc/
  api.py
  catalog.py
  read_service.py
  graph.py
  ai_layers.py
  ...
```

`data/ai_companies.json` becomes the canonical curated universe. Python owns
its validation and all generated artifacts. The frontend contains no copied
catalog or generated visualization payload.

## Runtime architecture

```text
data/ai_companies.json --------> catalog service -----+
                                                       |
PostgreSQL issuer/filing/parse data -> aggregate query +--> FastAPI read API
                                                       |
data/generated/{graph,layers}.json --------------------+
                                                              |
                                                              v
                                                    Vite TypeScript pages
```

During frontend development, Vite runs on port 5173 and proxies `/api/v1/*`
to FastAPI on port 8000. This avoids development-only CORS configuration.

For the normal local and production-style workflow, Vite builds to
`frontend/dist/`. FastAPI registers every API route first, then mounts that
directory at `/`. Therefore `/api/v1/*` remains backend-owned and `/` serves
the compiled research homepage. A missing production build produces an
explicit startup or health diagnostic rather than silently serving the old
`web/` directory.

## Catalog and database merge

The new `fdc.catalog` module loads and validates the ordered AI universe. The
catalog is read once per process and can be refreshed by restarting the
service; Vite and uvicorn reload modes already restart on source changes.

The database query aggregates issuers, filings, and the latest parse state in
one query. It must not issue one query per company. Duplicate issuer rows with
the same ticker use the existing canonical rule: newest filing date, then
newest record, then CIK as a deterministic tie-breaker.

The merge key is normalized uppercase ticker. Every catalog company appears
exactly once even when no issuer or filing exists in the database. Database
issuers that are outside the curated AI universe are not included in this
directory endpoint; they remain addressable through existing ticker-specific
read endpoints.

### Directory state

The API derives one `ingestion_status` for each catalog company:

- `parsed`: the latest filing has a current successful parse.
- `failed`: the latest available parse attempt failed.
- `unavailable`: at least one filing exists, but the latest filing has no
  current usable parse.
- `not_ingested`: no filing is persisted for the catalog ticker.

`research_available` is true when the canonical issuer has at least one
persisted filing. A false value prevents the frontend from linking users to a
known 404 state.

## API contract

### `GET /api/v1/companies`

Query parameters:

- `query`: case-insensitive ticker or company-name substring.
- `layer`: exact catalog layer identifier.
- `segment`: exact segment name within the selected or any layer.
- `ingestion_status`: one of the four directory states.
- `limit`: page size, default 25, allowed range 1–100.
- `offset`: zero-based offset, default 0.

Filtering happens before total calculation and pagination. The default sort is
the declared layer order, declared segment order, then ticker. Search does not
silently reorder results.

Each company contains:

```json
{
  "ticker": "NVDA",
  "name": "NVIDIA",
  "sector": "Information Technology",
  "industry": "Semiconductors",
  "layer": "silicon",
  "layer_name": "芯片与半导体",
  "segment": "算力芯片",
  "description": "...",
  "cik": "0001045810",
  "latest_filing_date": "2026-08-26",
  "latest_filing_status": "success",
  "ingestion_status": "parsed",
  "filing_count": 91,
  "research_available": true
}
```

Catalog-only values use `null` for `cik`, `latest_filing_date`, and
`latest_filing_status`, zero for `filing_count`, and false for
`research_available`. Missing values are never replaced with invented facts.

The response retains `query`, `limit`, `offset`, `total`, and `companies` and
adds normalized active filters. `total` is the filtered total, not the current
page length.

### `GET /api/v1/catalog/layers`

Returns layers and segments in declared order, with catalog counts. This is
the only source for directory filter options; the frontend does not duplicate
the layer taxonomy.

### Visualization endpoints

- `GET /api/v1/visualizations/graph`
- `GET /api/v1/visualizations/layers`

These endpoints return the validated contents of the generated files. Missing
or stale artifacts produce explicit API errors with diagnostics. The browser
never reads repository paths or generated JSON files directly.

Existing ticker, filing, fact, statement, section, table, evidence, and parse-
run read endpoints remain compatible.

## Frontend design

### Shared infrastructure

`api/client.ts` owns base paths, query encoding, response parsing, abortable
requests, and normalized API errors. `api/types.ts` defines the exact response
contracts consumed by pages. This phase uses maintained TypeScript interfaces
rather than adding OpenAPI code generation.

Shared components are small DOM-producing modules rather than a framework-
specific abstraction. They use `textContent`, attribute setters, and explicit
element creation for API data. Untrusted API content is not interpolated into
`innerHTML`.

The shared visual system keeps the existing ledger green, filing blue, paper
white, amber, and error palette, plus the Charter-style serif and Avenir/system
sans typography. The migration should preserve the current recognizable
research-led design rather than restyle all four pages.

### Directory page

Search, layer, segment, ingestion status, page, and page size are synchronized
to URL query parameters. Reloading or sharing the URL restores the same view.
A filter change resets the page to one. Requests are abortable so an older
response cannot overwrite a newer search.

The default page size is 25, with 25, 50, and 100 options. Controls show the
visible range, filtered total, previous/next actions, and bounded page-number
links. Buttons expose disabled state and accessible labels at boundaries.

Desktop uses an information-dense table. The company cell includes ticker,
name, and the catalog description; other columns show layer/segment,
sector/industry, latest filing, ingestion state, and filing count. Narrow Web
viewports use responsive cards with the same information and no horizontal
page overflow.

Rows with `research_available=true` link to
`company.html?ticker=<encoded ticker>`. Other rows show `Not ingested` as an
explicit non-action.

### Company research page

The existing filing timeline, facts, statements, disclosures, and evidence
interactions remain behaviorally compatible. The page moves to shared styles,
types, formatting, API error handling, and navigation. Existing safeguards
against stale evidence responses remain in place.

### Graph and layers pages

The graph keeps its current 3D interaction, ticker-based node identity,
filters, framing, and company/link detail behavior. `3d-force-graph` becomes a
versioned npm dependency rather than a runtime CDN import.

The layer viewer keeps its hierarchy, collapse behavior, and framing. D3 also
becomes a versioned npm dependency. Both pages fetch through the visualization
API and provide visible load and error states.

## Loading, empty, and failure behavior

Every request-driven region has four explicit states: loading, content, empty,
and error. Directory errors offer a retry action and retain the current URL
filters. Empty results explain which filters are active. A missing generated
visualization identifies the regeneration command in backend diagnostics, but
the browser displays a concise user-facing message rather than a filesystem
path or stack trace.

Client code distinguishes aborted requests from failures. Aborted stale
requests do not update live regions or produce console errors.

## Accessibility and responsive behavior

- All search and filter controls have visible labels.
- Search submits with Enter.
- Focus indicators remain visible and meet the existing color system.
- Status changes use restrained live regions.
- Pagination is keyboard-operable and identifies the current page.
- Tables retain semantic headers on desktop; the narrow-card presentation
  preserves programmatic labels.
- Motion respects `prefers-reduced-motion`.
- The supported minimum viewport width is 320 pixels.

## Security boundaries

The frontend remains read-only and sends no non-GET API methods. API-provided
names, descriptions, filing excerpts, captions, and diagnostics are treated as
untrusted text. SEC links must use validated HTTP(S) URLs and external links
retain `noopener noreferrer`.

The Vite proxy is a development convenience, not an authorization boundary.
Static mounting remains last in FastAPI route order so a frontend path cannot
shadow `/api/v1/*`.

## Testing strategy

### Backend

- Unit tests validate catalog schema, unique tickers, declared layers and
  segments, stable order, merge behavior, and derived ingestion states.
- Integration tests validate all 211 catalog companies, layer counts, search,
  combined filters, deterministic sorting, pagination boundaries, catalog-only
  rows, parsed rows, and duplicate-ticker issuer selection.
- Visualization endpoint tests validate successful payloads and explicit
  unavailable states.

### Frontend

- Vitest with a DOM environment covers query-string parsing, URL state updates,
  abort handling, loading/error/empty rendering, responsive row data, and
  pagination boundaries.
- TypeScript checking and the Vite production build are required gates.

### Browser acceptance

Playwright runs against a real FastAPI server and built frontend. Coverage
includes desktop and 390-pixel directory layouts, cross-page navigation,
search, each filter, pagination, page-size changes, URL restoration, a
not-ingested company, the NVDA research path, the graph canvas, layer collapse,
keyboard interaction, and console/runtime errors.

Existing Python tests, Ruff, compile checks, and real browser screenshot review
remain required. A structural test or successful build alone is not sufficient
for interactive pages.

## Migration and compatibility

Migration is complete only when all tracked production frontend source and
generated data have moved out of `web/`, all four pages pass browser acceptance
from their existing URLs, and no Python module reads from or writes to `web/`.

Tracked production assets are removed from `web/` only after the new build
passes. The directory itself may remain because unrelated untracked files are
preserved; `web/_dbg_index.html` is user-owned and must not be moved, deleted,
or committed as part of this migration without separate approval.

The README will document:

- backend installation and database startup;
- frontend dependency installation;
- two-process development mode;
- production frontend build followed by uvicorn on port 8000;
- regeneration of graph and layer payloads.

Direct `file://` viewing is intentionally removed. Existing public page URLs
and API ticker semantics remain compatible.

## Acceptance criteria

1. `/api/v1/companies` reports 211 companies before filtering and paginates
   deterministically with a default page size of 25.
2. Catalog-only companies appear as `not_ingested` with no research link.
3. NVDA retains its database-backed filing count, latest status, and working
   company research page.
4. Layer and segment filters use backend-provided taxonomy and counts.
5. `/`, `/company.html`, `/graph.html`, and `/layers.html` are produced by the
   Vite build and work through port 8000.
6. No frontend module directly reads canonical or generated repository JSON.
7. No backend generator reads from or writes to `web/`.
8. Desktop and narrow browser checks complete without page overflow, stale
   responses, console errors, or broken keyboard navigation.
9. The full Python, TypeScript, build, and browser suites pass.
