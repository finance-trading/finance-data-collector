# SEC Filing Parsing and Research Web Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse every locally archived 10-K/10-Q filing, persist versioned facts and evidence in PostgreSQL, support incremental and forced re-parsing, and expose a read-only API plus a first company research page.

**Architecture:** The existing `sec/<TICKER>/` archive is the historical input and remains immutable. A write-side parser service scans filing packages, computes artifact-set identities, combines an EdgarTools adapter for standard XBRL/statements with deterministic HTML/XML extraction for sections/tables, and commits versioned results atomically. FastAPI and the web client read only current parse results and evidence links.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, Alembic, PostgreSQL/SQLite test backend, Pydantic settings, FastAPI, Typer, pinned `edgartools`, `lxml`/BeautifulSoup, pytest, and the existing local SEC downloader.

**Spec:** `docs/superpowers/specs/2026-09-25-sec-filing-parsing-platform-design.md`

## Global Constraints

- Historical input is the existing `sec/<TICKER>/` archive; parsing never redownloads historical packages.
- Eligible forms are `10-K`, `10-Q`, `10-K/A`, and `10-Q/A`; missing packages remain explicit ingest gaps.
- Every extracted value carries filing/accession, parse run, parser version, artifact hash, and an evidence locator.
- Incremental identity is `(issuer, accession, artifact_set_hash, parser_version, parser_modules)`.
- Parser versions are immutable; a new version creates a new result and never deletes the previous result.
- At most one successful parse result per filing is marked `current` for the configured serving parser version.
- The write path is CLI/worker only; the HTTP API is read-only.
- Missing, unsupported, malformed, conflicting, and unavailable data remain explicit states; no inference fills gaps.
- SEC network requests, when used by the existing downloader, require the configured contact User-Agent.
- Tests must run offline against fixed fixtures; live SEC smoke tests are opt-in and separate.

## File Map

- `pyproject.toml`, `uv.lock`: pin EdgarTools and parser runtime dependencies.
- `src/fdc/config.py`: parser/database settings and version configuration.
- `src/fdc/db.py`: SQLAlchemy engine, session factory, and transaction helper.
- `src/fdc/models.py`: issuer, filing, artifact, parse, fact, statement, section, table, and evidence models.
- `alembic.ini`, `alembic/env.py`, `alembic/versions/`: schema migrations.
- `src/fdc/archive.py`: local archive scanner, artifact classifier, hashes, and primary-document selection.
- `src/fdc/contracts.py`: typed parser output and diagnostics contracts independent of EdgarTools classes.
- `src/fdc/parsers/edgartools_adapter.py`: pinned EdgarTools integration for local filings/XBRL/statements.
- `src/fdc/parsers/html_parser.py`: deterministic section/table/footnote extraction.
- `src/fdc/parsers/disclosures.py`: typed debt, lease, liquidity, and generic table extraction.
- `src/fdc/parsers/service.py`: one-filing parse transaction and versioned result state.
- `src/fdc/sync.py`: ticker/full-store scan, incremental selection, retries, and run checkpoints.
- `src/fdc/cli.py`: `fdc parse` and parse-run inspection commands.
- `src/fdc/api.py`, `src/fdc/read_service.py`: read-only API and query shaping.
- `web/company.html`, `web/company.js`, `web/data/company.css`: first research page.
- `tests/fixtures/filings/`: small representative filing packages.
- `tests/unit/`, `tests/integration/`, `tests/acceptance/`: parser, storage, API, and browser-contract tests.

### Task 1: Runtime Bootstrap and Dependency Pinning

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/fdc/config.py`
- Create: `src/fdc/db.py`
- Create: `tests/unit/test_runtime.py`

**Interfaces:**
- Produces `Settings.parser_version: str`, `Settings.edgartools_version: str | None`, `Settings.sec_root: str`, `Settings.database_url: str`.
- Produces `get_engine() -> sqlalchemy.Engine`, `SessionLocal`, and `session_scope() -> Iterator[Session]`.

- [x] **Step 1: Write failing runtime tests**

```python
def test_parser_settings_are_explicit(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setenv("FDC_PARSER_VERSION", "filing-parser-v1")
    settings = get_settings()
    assert settings.parser_version == "filing-parser-v1"
    assert settings.sec_root == "./sec"


def test_session_scope_rolls_back_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setenv("FDC_DATABASE_URL", f"sqlite:///{tmp_path / 'collector.db'}")
    with pytest.raises(RuntimeError):
        with session_scope() as session:
            session.execute(text("SELECT 1"))
            raise RuntimeError("rollback")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_runtime.py -q`

Expected: FAIL because parser settings and database helpers do not exist.
Verified: `ModuleNotFoundError: No module named 'fdc.db'`.

- [x] **Step 3: Add dependencies and runtime helpers**

Add `edgartools` with a pinned compatible release, plus `beautifulsoup4` and
`lxml` if not already present. Add parser settings with defaults `./sec` and
`filing-parser-v1`; keep SEC User-Agent validation. Configure SQLAlchemy with
`pool_pre_ping=True`, SQLite compatibility for tests, and a context manager that
commits on success and rolls back/closes on error.

- [x] **Step 4: Run tests and import checks**

Run: `uv sync && pytest tests/unit/test_runtime.py -q`

Expected: PASS; importing `fdc.db` must not require a live PostgreSQL server.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/fdc/config.py src/fdc/db.py tests/unit/test_runtime.py
git commit -m "build: bootstrap filing parser runtime"
```

### Task 2: Versioned Database Schema and Migration

**Files:**
- Create: `src/fdc/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_filing_parser_platform.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_models.py`
- Create: `tests/integration/test_schema.py`

**Interfaces:**
- Produces SQLAlchemy models `Issuer`, `Filing`, `Artifact`, `ParseRun`, `FilingParse`, `XbrlFact`, `StatementLine`, `FilingSection`, `ExtractedTable`, and `EvidenceLocator`.
- Produces `create_all_for_tests(engine)` and migration target metadata.

- [x] **Step 1: Write failing model and constraint tests**

```python
def test_filing_accession_is_unique(session):
    issuer = Issuer(cik="0000320193", name="Apple Inc.")
    session.add(issuer)
    session.flush()
    session.add(Filing(issuer_id=issuer.id, accession_number="0000320193-24-000001", form="10-K"))
    session.commit()
    session.add(Filing(issuer_id=issuer.id, accession_number="0000320193-24-000001", form="10-K"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_fact_has_version_and_evidence(session):
    fact = XbrlFact(
        concept="Revenue",
        parser_version="filing-parser-v1",
        value_numeric=100.0,
        unit="USD",
        evidence_locator_id=evidence.id,
    )
    session.add(fact)
    session.commit()
    assert fact.parser_version == "filing-parser-v1"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_models.py tests/integration/test_schema.py -q`

Result: FAILED before Step 3 (no `fdc.models`, no `alembic.ini`), then green after
Steps 3-4: `24 passed, 1 skipped` (the skip is the PostgreSQL case, which needs
`docker compose up -d postgres`).

- [x] **Step 3: Implement models and indexes**

Use UUID primary keys and UTC-aware timestamps. Add unique `(issuer_id,
accession_number)`, unique artifact `(filing_id, relative_path, sha256)`,
parse identity `(filing_id, artifact_set_hash, parser_version,
parser_modules_hash)`, and partial uniqueness for one current successful parse
per filing/serving version. Add indexes for ticker lookup, filing date/form,
fact concept/period, parse status, and evidence lookup. Store dimensions,
diagnostics, normalized table rows, and source metadata in JSON columns.

- [x] **Step 4: Create and exercise the migration**

Run:

```bash
uv run alembic upgrade head
uv run pytest tests/unit/test_models.py tests/integration/test_schema.py -q
```

Result: `alembic upgrade head`, `alembic downgrade base`, and a second
`upgrade head` all succeed against SQLite; the migrated columns, indexes, and
named constraints are asserted against `Base.metadata` in
`tests/integration/test_schema.py`. The PostgreSQL round-trip is covered by the
same module and skips when no container is reachable.

- [x] **Step 5: Commit**

```bash
git add src/fdc/models.py alembic.ini alembic src/fdc/db.py .env.example tests/conftest.py \
  tests/unit/test_models.py tests/integration/test_schema.py
git commit -m "feat: add versioned filing parser schema"
```

### Task 3: Local Archive Scanner and Parser Contracts

**Files:**
- Create: `src/fdc/contracts.py`
- Create: `src/fdc/archive.py`
- Create: `tests/fixtures/filings/MSFT/filings_index.json`
- Create: `tests/fixtures/filings/MSFT/10-K/0000000000-24-000001/`
- Create: `tests/fixtures/filings/MSFT/10-Q/0000000000-25-000002/`
- Create: `tests/unit/test_archive.py`

**Interfaces:**
- `scan_ticker_archive(sec_root: Path, ticker: str, forms: set[str]) -> ArchiveScan`.
- `ArchiveScan.filings: list[LocalFiling]`, `ArchiveScan.gaps: list[ArchiveGap]`.
- `LocalFiling.artifact_set_hash: str`, `LocalFiling.primary_document: Path | None`.
- `classify_artifact(path: Path) -> ArtifactRole` and `sha256_file(path: Path) -> str`.
- `ParserOutput` contains facts, statements, sections, tables, evidence, diagnostics, and status.

- [x] **Step 1: Write failing scanner tests**

```python
def test_scan_normalizes_forms_and_hashes_artifacts(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", {"10-K", "10-Q", "10-K/A", "10-Q/A"})
    assert [filing.form for filing in scan.filings] == ["10-K", "10-Q"]
    assert scan.filings[0].accession == "0000000000-24-000001"
    assert len(scan.filings[0].artifact_set_hash) == 64
    assert scan.filings[0].primary_document.suffix in {".htm", ".html", ".xml"}


def test_missing_package_is_explicit_gap(tmp_path):
    (tmp_path / "MSFT").mkdir()
    (tmp_path / "MSFT" / "filings_index.json").write_text(
        json.dumps({"filings": [{"form": "10-K", "date": "2024-01-01", "accession": "a", "directory": "10-K/a"}]})
    )
    scan = scan_ticker_archive(tmp_path, "MSFT", {"10-K"})
    assert scan.gaps[0].code == "PACKAGE_MISSING"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_archive.py -q`

Result: FAILED with `ModuleNotFoundError: No module named 'fdc.archive'` before Step 3,
then green: `49 passed`.

- [x] **Step 3: Implement scanner and typed contracts**

Read only the ticker's `filings_index.json`; validate parallel metadata without
deleting files; classify `.txt` by content/name rather than extension; skip
images from parsing while retaining their artifact metadata; choose the indexed
primary document first and then use deterministic HTML/XML ranking. Hash the
sorted tuple `(relative_path, byte_size, sha256)` with SHA-256. Define stable
diagnostic codes for missing index, malformed index, missing package, missing
primary, unsupported form, and unreadable artifact.

Implemented as `DiagnosticCode` (plus `INVALID_INDEX_RECORD`, `INVALID_ACCESSION`
and `PACKAGE_EMPTY`, which a real archive needs: dated MSFT packages exist as
empty directories). The scanner records `gaps` for blocking problems and
`skipped` for records outside the requested form set, so nothing is dropped
silently.

- [x] **Step 4: Run tests and a real local scan**

Run: `uv run pytest tests/unit/test_archive.py -q && uv run python -m fdc.archive MSFT --sec-root sec`

Result: tests green; the real MSFT scan finishes offline in ~1s and reports
`555 index records, 100 eligible filings, 37 gaps, 418 skipped`
(24 `PACKAGE_MISSING`, 13 `PACKAGE_EMPTY`, the rest non-10-K/10-Q forms), with
10-Q=73, 10-K=25, 10-Q/A=2 eligible.

- [x] **Step 5: Commit**

```bash
git add src/fdc/contracts.py src/fdc/archive.py tests/fixtures/filings tests/unit/test_archive.py
git commit -m "feat: scan local SEC filing archives"
```

### Task 4: EdgarTools XBRL and Statement Adapter

**Files:**
- Create: `src/fdc/parsers/__init__.py`
- Create: `src/fdc/parsers/edgartools_adapter.py`
- Create: `tests/fixtures/edgar/`
- Create: `tests/unit/test_edgartools_adapter.py`

**Interfaces:**
- `EdgarToolsAdapter.parse(local_filing: LocalFiling) -> ParserOutput`.
- `normalize_fact(raw_fact: object, filing: LocalFiling, parser_version: str) -> FactDraft`.
- `period_type(start: date | None, end: date | None) -> Literal[...]`.

- [ ] **Step 1: Write failing adapter tests against a fixture double**

```python
def test_adapter_preserves_period_identity_and_dimensions(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)
    revenue = next(fact for fact in output.facts if fact.concept == "Revenue")
    assert revenue.start_date == date(2024, 1, 1)
    assert revenue.end_date == date(2024, 3, 31)
    assert revenue.period_type == "quarter"
    assert revenue.dimensions == {"segment": "cloud"}


def test_ytd_is_not_classified_as_quarter():
    assert period_type(date(2024, 1, 1), date(2024, 9, 30)) == "ytd"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_edgartools_adapter.py -q`

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Probe and pin the installed EdgarTools API**

Use a checked-in fixture and a small adapter probe to identify the supported
local-file/package entry point for the pinned EdgarTools release. Keep all
EdgarTools imports inside `edgartools_adapter.py`; never leak EdgarTools model
classes into database code. If the release cannot open a local package,
parse its downloaded XBRL XML/Inline XBRL artifacts through the adapter's
fallback and record `mode="raw-xbrl-fallback"` in diagnostics.

- [ ] **Step 4: Implement normalization**

Map facts and statement rows into `FactDraft`/`StatementDraft`, preserve
namespace/concept/label/unit/decimals/start/end/dimensions/filing metadata,
classify instant/quarter/annual/YTD using `(start, end)`, and choose no value
when a raw fact is malformed. Include evidence draft data for each emitted
fact.

- [ ] **Step 5: Run tests and lint**

Run: `pytest tests/unit/test_edgartools_adapter.py -q && ruff check src/fdc/parsers/edgartools_adapter.py`

Expected: PASS offline with the fixture double and no network requests.

- [ ] **Step 6: Commit**

```bash
git add src/fdc/parsers tests/fixtures/edgar tests/unit/test_edgartools_adapter.py pyproject.toml uv.lock
git commit -m "feat: add EdgarTools XBRL adapter"
```

### Task 5: HTML Sections, Tables, and Typed Disclosures

**Files:**
- Create: `src/fdc/parsers/html_parser.py`
- Create: `src/fdc/parsers/disclosures.py`
- Create: `tests/fixtures/filings/with_debt/`
- Create: `tests/unit/test_html_parser.py`
- Create: `tests/unit/test_disclosures.py`

**Interfaces:**
- `parse_html_document(path: Path, filing: LocalFiling, parser_version: str) -> ParserOutput`.
- `extract_sections(document: HtmlDocument) -> list[SectionDraft]`.
- `extract_tables(document: HtmlDocument) -> list[TableDraft]`.
- `classify_disclosure(table: TableDraft) -> DisclosureType`.

- [ ] **Step 1: Write failing section/table tests**

```python
def test_sections_keep_heading_order_and_source_locator(debt_fixture):
    output = parse_html_document(debt_fixture, local_filing, "filing-parser-v1")
    mdna = next(section for section in output.sections if section.section_type == "md_and_a")
    assert mdna.order > 0
    assert mdna.evidence.locator_type in {"heading", "html_id"}
    assert "liquidity" in mdna.text.lower()


def test_debt_maturity_table_is_typed(debt_fixture):
    output = parse_html_document(debt_fixture, local_filing, "filing-parser-v1")
    table = next(table for table in output.tables if table.table_type == "debt_maturity")
    assert table.rows[0]["period"] == "2027"
    assert table.status == "parsed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_html_parser.py tests/unit/test_disclosures.py -q`

Expected: FAIL because narrative/table parsers are absent.

- [ ] **Step 3: Implement deterministic HTML parsing**

Use `lxml`/BeautifulSoup to normalize text, preserve heading hierarchy and
order, identify standard 10-K/10-Q item headings, extract tables with row and
column labels, and store a stable raw-fragment hash. Do not depend on CSS
classes that vary by issuer. Keep malformed-table diagnostics attached to the
table rather than aborting the filing.

- [ ] **Step 4: Implement typed disclosure classification**

Classify by caption/nearby heading and column vocabulary into
`debt_maturity`, `lease_maturity`, `contractual_obligation`, `segment`,
`revenue_disaggregation`, `liquidity`, or `generic`. Preserve the normalized
rows, original labels, units, period hints, extraction method, and confidence.

- [ ] **Step 5: Run parser tests and fixture snapshots**

Run: `pytest tests/unit/test_html_parser.py tests/unit/test_disclosures.py -q`

Expected: PASS; snapshot changes must show only intentional locator/text normalization differences.

- [ ] **Step 6: Commit**

```bash
git add src/fdc/parsers/html_parser.py src/fdc/parsers/disclosures.py tests/fixtures/filings/with_debt tests/unit/test_html_parser.py tests/unit/test_disclosures.py
git commit -m "feat: extract filing sections and disclosures"
```

### Task 6: Atomic Filing Parse Service and Incremental Sync

**Files:**
- Create: `src/fdc/parsers/service.py`
- Create: `src/fdc/sync.py`
- Create: `tests/unit/test_parse_service.py`
- Create: `tests/integration/test_incremental_parse.py`

**Interfaces:**
- `parse_one_filing(session: Session, local_filing: LocalFiling, settings: Settings, force: bool = False) -> FilingParse`.
- `select_pending_filings(session: Session, scan: ArchiveScan, parser_version: str, force: bool = False) -> list[LocalFiling]`.
- `parse_ticker(session_factory, ticker: str, sec_root: Path, force: bool = False) -> ParseRun`.
- `parse_all(session_factory, sec_root: Path, force: bool = False) -> list[ParseRun]`.

- [ ] **Step 1: Write failing idempotency and reparse tests**

```python
def test_second_parse_skips_same_identity(session_factory, fixture_root):
    first = parse_ticker(session_factory, "MSFT", fixture_root)
    second = parse_ticker(session_factory, "MSFT", fixture_root)
    assert first.success_count == 2
    assert second.input_count == 0


def test_parser_version_creates_new_result_without_deleting_old(session_factory, fixture_root, monkeypatch):
    parse_ticker(session_factory, "MSFT", fixture_root)
    monkeypatch.setenv("FDC_PARSER_VERSION", "filing-parser-v2")
    get_settings.cache_clear()
    run = parse_ticker(session_factory, "MSFT", fixture_root)
    assert run.success_count == 2
    with session_factory() as session:
        assert session.scalar(select(func.count(FilingParse.id))) == 4


def test_one_failed_filing_is_partial_and_retryable(session_factory, fixture_root, monkeypatch):
    monkeypatch.setattr("fdc.parsers.service.parse_html_document", fail_for_one_accession)
    run = parse_ticker(session_factory, "MSFT", fixture_root)
    assert run.status == "partial"
    assert run.failure_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_parse_service.py tests/integration/test_incremental_parse.py -q`

Expected: FAIL because orchestration and parse persistence are absent.

- [ ] **Step 3: Implement per-filing atomic parse**

Create a `ParseRun`, persist issuer/filing/artifact metadata, call both parser
adapters, attach every draft to evidence and parse run, and commit all filing
rows in one transaction. On failure, rollback emitted child rows, persist a
failure `FilingParse` with diagnostics, and continue the parent run. Mark a
successful result current only after all required parser modules finish.

- [ ] **Step 4: Implement incremental selection and checkpoints**

Compare scan identities against successful current results. Skip only exact
identity matches. Reparse on `--force`, parser version/module hash changes, or
artifact-set hash changes. Store `input_count`, `success_count`,
`failure_count`, current accession checkpoint, and structured errors on the
run. Ensure a process interruption can resume from the last committed filing.

- [ ] **Step 5: Run integration tests**

Run: `pytest tests/unit/test_parse_service.py tests/integration/test_incremental_parse.py -q`

Expected: PASS, including no duplicate current results, versioned reruns, and partial failure recovery.

- [ ] **Step 6: Commit**

```bash
git add src/fdc/parsers/service.py src/fdc/sync.py tests/unit/test_parse_service.py tests/integration/test_incremental_parse.py
git commit -m "feat: add incremental filing parse service"
```

### Task 7: CLI Operations and Read-Only API

**Files:**
- Modify: `src/fdc/cli.py`
- Create: `src/fdc/read_service.py`
- Create: `src/fdc/api.py`
- Create: `tests/unit/test_cli_parse.py`
- Create: `tests/integration/test_api_filings.py`

**Interfaces:**
- CLI commands: `fdc parse filings --ticker TICKER`, `fdc parse filing --accession ACCESSION`, `fdc parse filings --all`, `fdc parse-runs show RUN_ID`.
- `get_company(ticker: str) -> CompanyView`.
- `list_filings(ticker: str, form: str | None, limit: int, offset: int) -> FilingListView`.
- `get_filing(accession: str) -> FilingView`.
- `get_statement(accession: str, statement_type: str) -> StatementView`.
- `get_facts(accession: str, concept: str | None) -> FactView`.
- FastAPI routes exactly as listed in the design spec.

- [ ] **Step 1: Write failing CLI/API tests**

```python
def test_parse_filings_cli_passes_force_and_forms(cli_runner, monkeypatch):
    called = {}
    monkeypatch.setattr("fdc.cli.parse_ticker", lambda **kwargs: called.update(kwargs) or fake_run())
    result = cli_runner.invoke(app, ["parse", "filings", "--ticker", "MSFT", "--force", "--forms", "10-K,10-Q"])
    assert result.exit_code == 0
    assert called["force"] is True
    assert called["forms"] == {"10-K", "10-Q"}


def test_filing_api_exposes_evidence(client, seeded_database):
    response = client.get("/api/v1/filings/0000000000-24-000001/facts?concept=Revenue")
    assert response.status_code == 200
    assert response.json()["facts"][0]["evidence"]["accession"] == "0000000000-24-000001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cli_parse.py tests/integration/test_api_filings.py -q`

Expected: FAIL because parse commands and API routes are absent.

- [ ] **Step 3: Implement CLI commands**

Add Typer subcommands for ticker, accession, forms, force, parser version, and
all-ticker scope. Print run ID, counts, status, and explicit failures. Do not
print raw filing contents or credentials. Add run inspection with accession-
level diagnostics.

- [ ] **Step 4: Implement read service and API**

Shape API responses from current successful parse results only by default;
include parser version, filing/report dates, status, evidence IDs, and explicit
unavailable fields. Add pagination and form/concept filters. Return 404 for
unknown ticker/accession and 409/422 for unavailable or failed parse outputs,
with diagnostics in the response body.

- [ ] **Step 5: Run API tests and OpenAPI import**

Run: `pytest tests/unit/test_cli_parse.py tests/integration/test_api_filings.py -q && python -c 'from fdc.api import app; print(len(app.routes))'`

Expected: PASS and the app imports without a database connection at import time.

- [ ] **Step 6: Commit**

```bash
git add src/fdc/cli.py src/fdc/read_service.py src/fdc/api.py tests/unit/test_cli_parse.py tests/integration/test_api_filings.py
git commit -m "feat: expose filing parse operations and read API"
```

### Task 8: Company Research Page and End-to-End Acceptance

**Files:**
- Create: `web/company.html`
- Create: `web/company.js`
- Create: `web/data/company.css`
- Create: `tests/acceptance/test_company_page.py`
- Create: `docs/runbook.md`
- Modify: `README.md`

**Interfaces:**
- Browser route: `/company.html?ticker=MSFT`.
- API contract consumed by the page: company summary, filings list, statements, facts, sections, tables, and evidence links.

- [ ] **Step 1: Write failing page contract tests**

```python
def test_company_page_has_filing_and_statement_mounts():
    html = Path("web/company.html").read_text()
    assert 'id="filings"' in html
    assert 'id="income-statement"' in html
    assert 'id="evidence"' in html


def test_company_page_fetches_read_api():
    script = Path("web/company.js").read_text()
    assert "/api/v1/companies/" in script
    assert "/filings" in script
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/acceptance/test_company_page.py -q`

Expected: FAIL because the company page does not exist.

- [ ] **Step 3: Implement the first research page**

Build a dense, scan-friendly company page with ticker/CIK header, filing list,
parse status, three statements, period-aware chart data, section/table links,
and an evidence panel. Use the existing static-data conventions and keep all
display data fetched from the API. Show `Unavailable`, `Unsupported`, and
`Parse failed` states visibly without substituting zeros.

- [ ] **Step 4: Add runbook and local startup instructions**

Document `docker compose up -d postgres`, `alembic upgrade head`, local SEC
archive prerequisites, `fdc parse filings --ticker`, forced/versioned reparse,
API startup, static page serving over HTTP, fixture tests, and the distinction
between local parsing and live downloading.

- [ ] **Step 5: Run full offline acceptance**

Run:

```bash
pytest -q
ruff check src tests
python -m compileall src
```

Expected: all deterministic tests pass, lint is clean, and the browser page
contract renders from an HTTP server without console errors. A Playwright smoke test
must click at least two filings and open at least one evidence link.

- [ ] **Step 6: Run optional PostgreSQL and live smoke checks**

Run:

```bash
docker compose up -d postgres
alembic upgrade head
FDC_SEC_USER_AGENT='Collector name@example.com' python scripts/live_sec_smoke.py
```

Expected: schema migration succeeds; live smoke is reported separately as
`PASS` or `SKIPPED`, never conflated with fixture-test success.

- [ ] **Step 7: Commit**

```bash
git add web/company.html web/company.js web/data/company.css tests/acceptance/test_company_page.py docs/runbook.md README.md
git commit -m "feat: add filing research page and runbook"
```

## Self-Review

- Spec coverage: Tasks 1-2 cover runtime/schema; Task 3 covers local archive and artifact identity; Tasks 4-5 cover EdgarTools and narrative/table extraction; Task 6 covers atomic persistence, incremental parsing, reparse, and checkpoints; Task 7 covers CLI/API; Task 8 covers web UI, browser verification, and runbook.
- Plan completeness: every task names files, interfaces, tests, commands, and expected outcomes without deferred implementation work.
- Type consistency: `LocalFiling`, `ArchiveScan`, `ParserOutput`, parser drafts, `parse_one_filing`, `select_pending_filings`, `parse_ticker`, and read-service methods are introduced before their consumers.
- Failure semantics: package/index gaps, parser failures, partial runs, unavailable sections, and live-smoke skip states remain explicit.
- Incremental semantics: the same artifact/parser identity skips; force, changed artifact hash, and parser/module version changes create a new result while preserving history.
