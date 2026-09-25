# SEC Filing Parsing and Research Web Platform

## Status

Design draft for review. The implementation is intentionally not started by
this document.

## Problem

The repository already contains downloaded SEC filing packages under
`sec/<TICKER>/`, including filing directories keyed by accession number,
`filings_index.json`, and selected `companyfacts.json` files. The next system
must parse every historical 10-K and 10-Q for a ticker, persist the results in
a database, support incremental parsing of new filings, and allow historical
filings to be re-parsed when the parser changes. The resulting data will be
served by a web application that can grow toward a Seeking Alpha-like
research product.

The system must preserve the distinction between source evidence and derived
interpretation. A database value without its accession, artifact, parser
version, and source locator is not an acceptable production result.

## Goals

1. Treat the existing local `sec/<TICKER>/` archive as the canonical source
   for historical backfills.
2. Parse all locally indexed 10-K and 10-Q filings, including amended forms
   when they are present in the index.
3. Extract standard XBRL facts and statements through an EdgarTools adapter.
4. Extract filing text, sections, tables, footnotes, and selected debt/
   liquidity disclosures through a separate HTML/XML parsing layer.
5. Store immutable source artifacts and versioned parse runs so outputs can be
   reproduced or replaced without destroying prior results.
6. Make new filings incremental: unchanged accession + unchanged artifact
   hash + successful current parser version is skipped.
7. Make re-parsing explicit and controllable at filing, ticker, parser-module,
   or full-universe scope.
8. Expose read-only API endpoints and a first web view for company filings and
   financial data.
9. Keep missing, unsupported, malformed, and unavailable fields explicit.

## Non-goals for the first release

- Analyst estimates, price targets, ratings, or market data.
- Automated investment conclusions or generated research prose.
- Complete semantic understanding of every issuer-specific table.
- Replacing the existing SEC downloader.
- Public write APIs or a resident scheduler.
- Cloud deployment, multi-tenant authorization, or billing.

## Design decisions

### Existing local archive is the historical source

The parser reads `sec/<TICKER>/filings_index.json` and resolves each record's
`directory` relative to that ticker directory. It does not rediscover or
redownload historical filings during a parse. The existing downloader remains
responsible for future synchronization with EDGAR.

The index is validated before work begins. A record is eligible only when its
form is `10-K`, `10-Q`, `10-K/A`, or `10-Q/A`, its accession is normalized, its
package directory exists, and at least one non-image primary document or XML
artifact can be identified. Missing packages are recorded as explicit ingest
gaps rather than silently omitted.

### Hybrid parser, not EdgarTools-only

EdgarTools is the standard-data adapter. It is responsible for filing metadata
where available, Inline XBRL/company-facts access, statement line items, units,
periods, dimensions, and standard concepts. Its version is pinned and recorded
in every parse run.

The deterministic source parser is responsible for capabilities that should
not depend on a high-level library's changing heuristics:

- primary-document discovery inside a package;
- HTML text and section boundaries;
- table extraction with source HTML preserved;
- footnote and note-heading capture;
- debt maturities, liquidity, lease, covenant, and other selected disclosure
  patterns;
- evidence locators and source snippets;
- graceful handling of malformed or issuer-specific documents.

The two outputs are merged by filing and source locator. They are not merged
by silently overwriting conflicting values. Conflicts are retained with a
comparison status and require a later normalization policy.

### Database is the serving store; raw files remain immutable

The local filing archive remains the raw source of truth. PostgreSQL stores
normalized metadata, parse outputs, evidence locators, and run state. Raw
artifact rows contain path, size, SHA-256, MIME/type classification, and the
source accession. The database never replaces the raw package with an opaque
serialized parser result.

## Architecture

```text
sec/<TICKER>/
  filings_index.json + accession packages
          |
          v
  Source scanner and artifact hasher
          |
          +--> Filing metadata normalizer
          +--> EdgarTools XBRL adapter
          +--> HTML/XML sections and tables parser
          +--> Evidence locator builder
          |
          v
  Versioned parse run + PostgreSQL transaction
          |
          +--> Read-only FastAPI API
          +--> Company filing page
          +--> Financial statement and metric views
```

The write path is a CLI/worker service. The web API is read-only. A later
queue or scheduler may invoke the same parse service, but must not introduce a
second persistence contract.

## Data model

All primary keys are UUIDs except provider identifiers that are naturally
string-valued. Timestamps are timezone-aware UTC. Rows carrying extracted
values include `source_filing_id`, `parse_run_id`, and an evidence reference.

### `issuer`

One SEC reporting issuer per normalized CIK. Fields include `id`, `cik`,
`name`, `ticker_hint`, `sic`, `exchange_hint`, and source timestamps. CIK is
unique. Ticker is not the issuer identity because it can change or be reused.

### `filing`

One logical SEC submission per `(issuer_id, accession_number)`. Fields include
`form`, `is_amended`, `filing_date`, `report_date`, `accepted_at` when present,
`fiscal_year`, `fiscal_period`, `primary_document`, `package_path`, SEC URL,
and index metadata. A unique constraint prevents duplicate accession rows.

### `artifact`

One file in a filing package. Fields include `relative_path`, `absolute_path`
or configured storage URI, `content_type`, `byte_size`, `sha256`, `role`
(`primary`, `xbrl`, `exhibit`, `image`, `text`, `unknown`), and classification
status. The same content hash may be referenced by multiple filings, but the
filing-relative path is retained for evidence.

### `parse_run`

One attempt to parse one or more filings. Fields include `id`, `scope_type`,
`scope_value`, `parser_version`, `edgartools_version`, `status`, `started_at`,
`finished_at`, `input_count`, `success_count`, `failure_count`, structured
error summary, and command/request metadata.

Allowed statuses are `queued`, `running`, `completed`, `partial`, `failed`,
and `cancelled`. A run is `completed` only when all eligible inputs finish
successfully. A filing-level failure makes a multi-filing run `partial` unless
no input succeeded.

### `filing_parse`

One result state for `(filing_id, artifact_set_hash, parser_version)`. It
records `parse_run_id`, parser module versions, status, diagnostics, and
whether the result is the current serving version. Old results remain
queryable for audit but are not returned by default.

### `xbrl_fact`

One normalized fact observation. Fields include `concept_namespace`, `concept`,
`label`, `value_numeric` or `value_text`, `unit`, `decimals`, `start_date`,
`end_date`, `period_type` (`instant`, `quarter`, `annual`, `ytd`, `other`),
dimensions JSON, `filed_at`, `form`, `accession`, and evidence reference.

The identity of a period is `(concept, unit, start_date, end_date,
dimensions)`, not only `end_date`. Comparative facts from later filings remain
distinct observations, with the serving layer applying an explicit latest-
vintage policy when requested.

### `statement_line`

Normalized presentation rows for income statement, balance sheet, cash flow,
equity, and segment statements. Fields include statement type, section/order,
display label, concept link when available, value/unit, period, dimensions, and
evidence. This preserves the issuer's statement presentation without treating
it as the only source of facts.

### `filing_section`

Extracted text sections keyed by filing and section type, such as `business`,
`risk_factors`, `md_and_a`, `financial_statements`, `controls`, and `notes`.
Fields include heading, normalized text, raw HTML fragment hash, ordering, and
evidence locator. Unsupported or missing sections have a status record rather
than fabricated text.

### `extracted_table`

One detected table or disclosure block. Fields include table type,
caption/heading, normalized rows and columns JSON, raw HTML fragment or hash,
period/context hints, extraction method, confidence/status, and evidence.
Initial typed table categories are `debt_maturity`, `lease_maturity`,
`contractual_obligation`, `segment`, `revenue_disaggregation`, and
`liquidity`; unclassified tables remain available as `generic`.

### `evidence_locator`

A reusable pointer containing filing, artifact, relative path, accession URL,
locator type (`html_id`, `heading`, `line_range`, `xbrl_fact`, `table_cell`,
or `snippet`), locator value, content hash, and optional excerpt. Evidence is
stored separately so API responses can link a fact to the exact source.

## Parsing pipeline

### 1. Scan and validate

The scanner loads `filings_index.json`, normalizes form/accession values,
checks package existence, classifies files without deleting any `.txt` file,
and computes an artifact manifest. It selects the primary document from index
metadata when available, then falls back to package ordering and XBRL/HTML
signals.

### 2. Establish parse identity

The parser computes an `artifact_set_hash` from the sorted relative path,
byte size, and SHA-256 of eligible artifacts. The parse identity is:

```text
(issuer, accession, artifact_set_hash, parser_version, parser_modules)
```

An existing successful identity is skipped unless an explicit `--force` or
reparse request is supplied.

### 3. Parse standard data

The EdgarTools adapter opens the local primary document/package where the
installed version supports local input. If a local API is unavailable, the
adapter uses the downloaded XBRL artifacts directly and records the fallback
mode. It emits facts and statement rows in an internal typed contract so the
database layer does not depend on EdgarTools model classes.

### 4. Parse narrative and tables

The HTML/XML parser extracts section headings, text, tables, notes, and typed
disclosures. It retains raw fragments or stable content hashes. Extraction
failures are scoped to the affected section/table and are recorded in
diagnostics; they do not discard successful XBRL facts.

### 5. Persist atomically

Filing metadata, artifacts, parse result state, facts, statements, sections,
tables, and evidence are committed in one transaction for that filing. The
run checkpoint advances only after commit. A retry creates a new parse attempt
and does not mutate a completed historical run.

## Incremental parsing and re-parsing

### Default incremental command

The planned operational interface is:

```bash
fdc parse filings --ticker MSFT
fdc parse filings --ticker MSFT --forms 10-K,10-Q
fdc parse filing --accession 0000950170-25-100235
```

The command first scans the local archive. It parses only eligible filings
without a successful current parse identity. It does not redownload files.

### Explicit reparse commands

```bash
fdc parse filing --accession <ACCESSION> --force
fdc parse filings --ticker MSFT --parser-version <VERSION> --force
fdc parse filings --all --module tables --force
```

The exact CLI names may be adjusted during implementation, but the semantic
contract is fixed: reparse is explicit, scoped, and leaves prior results
auditable.

### New filing flow

The existing downloader refreshes the local package and index. A subsequent
parse scan sees the new accession and processes only that filing. If an
existing accession gains a new exhibit or changes bytes, its artifact-set hash
changes and it is reparsed. A downloader failure is reported as a source
failure, never as successful parsing.

### Serving version

At most one parse result per filing is marked `current` for the configured
serving parser version. Historical versions remain queryable through an audit
endpoint. Changing the parser version does not delete facts; it creates a new
version and switches the current pointer only after a successful transaction.

## API and web boundary

The initial API is read-only:

```text
GET /api/v1/companies/{ticker}
GET /api/v1/companies/{ticker}/filings?form=10-K&limit=50
GET /api/v1/filings/{accession}
GET /api/v1/filings/{accession}/statements?statement_type=income
GET /api/v1/filings/{accession}/facts?concept=Revenue
GET /api/v1/filings/{accession}/sections/{section_type}
GET /api/v1/filings/{accession}/tables?table_type=debt_maturity
GET /api/v1/filings/{accession}/evidence/{evidence_id}
GET /api/v1/parse-runs/{run_id}
```

The first web page is a company research page with:

- ticker, legal name, CIK, SIC, and latest filing status;
- historical 10-K/10-Q list with filing/report dates and parse status;
- income statement, balance sheet, and cash-flow tables;
- metric trend charts backed by period-aware facts;
- sections and extracted tables with source links;
- explicit unavailable/parse-error indicators;
- a filing evidence drawer linking each value to its source artifact.

The web client does not calculate financial facts from raw HTML. It consumes
the API's normalized values and evidence links. UI work is kept separate from
the parser so data can be regenerated without rewriting the page.

## Error handling and data quality

- Missing `filings_index.json`, malformed index, missing package, or missing
  primary document creates a visible ingest error.
- A malformed XBRL fact is skipped only at fact level and logged with its
  accession/concept; the filing remains partial if required outputs are lost.
- A section/table parser failure stores an error diagnostic and leaves the
  corresponding output unavailable.
- Conflicting values from XBRL and rendered tables are both retained with
  source and extraction method. No silent preference is applied at ingest.
- Unsupported issuer-specific disclosures are labeled `unsupported` or
  `unavailable`, never inferred.
- Parse logs contain no credentials. SEC requests continue to require the
  configured User-Agent when the downloader is used.

## Testing and acceptance

Fixtures should use at least one annual filing, one quarterly filing, one
amended filing, one filing with Inline XBRL, and one filing with a debt or
lease maturity table. Tests must cover:

1. local archive scanning and accession normalization;
2. artifact classification and stable `artifact_set_hash`;
3. EdgarTools adapter output mapped into the internal contract;
4. XBRL period/dimension identity, including quarter versus YTD;
5. section/table extraction and evidence locators;
6. first full parse of all eligible filings;
7. second parse producing no duplicate current results;
8. new accession parsing only the new filing;
9. changed artifact or parser version causing a new parse result;
10. failed filing producing `partial`/`failed` status and retryability;
11. API responses exposing provenance and unavailable states;
12. browser smoke tests for filing navigation, statement rendering, chart data,
    and evidence links.

## Delivery phases

### Phase 1: local parser vertical slice

Implement local scanner, parse identity, EdgarTools adapter, basic XBRL facts,
SQLAlchemy schema/migration, one filing parse command, and fixture tests.

### Phase 2: historical backfill and incremental operation

Add all-ticker scan, checkpointed runs, amended filing policy, failure retry,
artifact manifests, and new-filing incremental parsing.

### Phase 3: narrative and disclosure extraction

Add sections, generic tables, typed debt/lease/liquidity extraction, evidence
locators, and parser-module versioning.

### Phase 4: read API and research web page

Add FastAPI read routes, company page, filing reader, statements, charts, and
source evidence UI.

### Phase 5: product expansion

Only after the data contract is stable: search, watchlists, comparison pages,
user annotations, market data, estimates, and editorial/research workflows.

## Open decisions for implementation planning

These are intentionally deferred until the implementation plan, not left as
runtime ambiguity:

- PostgreSQL-only integration versus a SQLite fixture backend for tests;
- exact EdgarTools local-file API supported by the pinned package version;
- first migration naming and SQLAlchemy relationship loading strategy;
- chart library and frontend bundling approach;
- retention policy for large raw HTML fragments in PostgreSQL versus local
  content-addressed storage.
