# SEC Identity and Submissions Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first SEC issuer, instrument, ticker-history, and submission-index pipeline with auditable raw storage, resumable CLI sync, and read-only API queries.

**Architecture:** A Python package separates domain models, SEC provider parsing, persistence, sync orchestration, CLI commands, and API routes. PostgreSQL stores normalized records and run state; immutable raw SEC responses live under a partitioned local filesystem root and are referenced by hash. The CLI owns writes, while FastAPI exposes only read queries and provenance.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, PostgreSQL 16, FastAPI, Typer, Pydantic v2, httpx, pytest, pytest-cov, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-13-sec-identity-submissions-design.md`

## Global Constraints

- The implementation is local-only in this phase; PostgreSQL is the normalized store and raw provider responses remain on the local filesystem.
- The first provider is the SEC official API: `company_tickers.json` for discovery and `data.sec.gov/submissions/CIK##########.json` for issuer and submissions data.
- The initial universe is US-listed company securities with a SEC CIK; no global exchanges, ETFs, funds, or non-CIK securities.
- `instrument_id` is permanent and never derived from ticker; ticker/exchange identifiers are time-bounded mappings.
- Preserve event/market time, disclosure/effective time, and fetch time separately; `as_of` must exclude facts not known by the requested instant.
- Every response is retained before normalization with source URL, provider, data domain, fetch time, SHA-256, and terms/authorization notes.
- The CLI is the only write path; API routes are read-only.
- Sync runs are idempotent, checkpointed, request-retried with error-aware exponential backoff, and distinguish `completed`, `partial`, `failed`, and `dead_letter`.
- Missing history and unavailable source fields remain explicit; do not infer or estimate values.
- Fixture replay is the deterministic acceptance path; live SEC smoke testing is separate and requires an explicit SEC identity header.

## File Map

- `pyproject.toml`, `.env.example`, `docker-compose.yml`: dependencies, local configuration, and PostgreSQL service.
- `src/fdc/config.py`, `src/fdc/db.py`, `src/fdc/models.py`: settings, engine/session factory, and SQLAlchemy models.
- `alembic/`: schema migration history.
- `src/fdc/raw_store.py`, `src/fdc/provenance.py`: immutable raw response storage and provenance helpers.
- `src/fdc/providers/sec/client.py`, `src/fdc/providers/sec/schemas.py`, `src/fdc/providers/sec/normalize.py`: SEC HTTP access, validated source shapes, and domain normalization.
- `src/fdc/sync/service.py`: run lifecycle, checkpoints, retries, and idempotent persistence.
- `src/fdc/cli.py`: Typer commands for sync and run inspection/retry.
- `src/fdc/api.py`, `src/fdc/read_service.py`: FastAPI application and read-only query services.
- `tests/fixtures/sec/`, `tests/unit/`, `tests/integration/`: replay fixtures and acceptance tests.
- `scripts/live_sec_smoke.py`: explicit, separately reported live connectivity check.

### Task 1: Bootstrap the Local Application

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `src/fdc/__init__.py`
- Create: `src/fdc/config.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- Produces `Settings` from `fdc.config.get_settings()`, with `database_url`, `raw_root`, `sec_user_agent`, `sec_timeout_seconds`, and retry settings.

- [ ] **Step 1: Write the failing test**

```python
def test_settings_require_explicit_sec_user_agent(monkeypatch):
    monkeypatch.delenv("FDC_SEC_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="FDC_SEC_USER_AGENT"):
        get_settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py::test_settings_require_explicit_sec_user_agent -q`
Expected: FAIL because `fdc.config` does not exist.

- [ ] **Step 3: Write minimal implementation**

Define a cached Pydantic settings object. Reject an empty SEC user-agent, default `raw_root` to `./data/raw`, and keep database/retry values configurable through `FDC_*` environment variables. Add project scripts for `fdc`, `pytest`, `alembic`, and `ruff`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .env.example docker-compose.yml src/fdc tests/unit/test_config.py
git commit -m "build: bootstrap local collector"
```

### Task 2: Create the Normalized Schema and Migration

**Files:**
- Create: `src/fdc/db.py`
- Create: `src/fdc/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_sec_identity_slice.py`
- Create: `tests/unit/test_models.py`
- Create: `tests/integration/test_schema.py`

**Interfaces:**
- Produces SQLAlchemy models `Issuer`, `Instrument`, `InstrumentIdentifier`, `SecSubmission`, `ProviderRun`, `RawObject`, and `Coverage`.
- Produces `get_session() -> Iterator[Session]` and a `session_scope()` context manager.

- [ ] **Step 1: Write failing model tests**

```python
def test_cik_is_ten_digit_and_unique(session):
    session.add(Issuer(cik="0000320193", legal_name="Example Corp"))
    session.commit()
    with pytest.raises(IntegrityError):
        session.add(Issuer(cik="0000320193", legal_name="Duplicate"))
        session.commit()

def test_accession_number_is_idempotency_key(session):
    assert SecSubmission.__table__.c.accession_number.unique is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_models.py -q`
Expected: FAIL because models and constraints are absent.

- [ ] **Step 3: Implement models and migration**

Use UUID primary keys for `issuer_id`, `instrument_id`, and `provider_run_id`. Store CIK as a ten-character string, accession number as a normalized unique string, timestamps as timezone-aware UTC values, and JSONB for requested scope/checkpoint/error details. Add indexes for CIK, ticker lookup, issuer submissions by disclosure time, and run status. Add a check preventing `valid_to < valid_from` and a unique constraint on `(provider, domain, accession_number)` where applicable.

- [ ] **Step 4: Run schema tests**

Run: `docker compose up -d postgres && alembic upgrade head && pytest tests/unit/test_models.py tests/integration/test_schema.py -q`
Expected: PASS with all tables and constraints created.

- [ ] **Step 5: Commit**

```bash
git add src/fdc/db.py src/fdc/models.py alembic.ini alembic tests/unit/test_models.py tests/integration/test_schema.py
git commit -m "feat: add SEC identity schema"
```

### Task 3: Implement Immutable Raw Storage and Provenance

**Files:**
- Create: `src/fdc/raw_store.py`
- Create: `src/fdc/provenance.py`
- Create: `tests/unit/test_raw_store.py`

**Interfaces:**
- `RawStore.write(*, provider: str, domain: str, scope_key: str, fetched_at: datetime, body: bytes, source_url: str, http_status: int, content_type: str, terms_note: str) -> RawObjectDraft`.
- `RawStore.path_for(draft: RawObjectDraft) -> Path`.
- `persist_raw_object(session: Session, draft: RawObjectDraft) -> RawObject`.

- [ ] **Step 1: Write failing storage tests**

```python
def test_raw_store_is_content_addressed_and_partitioned(tmp_path):
    draft = RawStore(tmp_path).write(
        provider="sec", domain="identities", scope_key="company_tickers",
        fetched_at=datetime(2026, 9, 13, tzinfo=UTC), body=b"{}",
        source_url="https://www.sec.gov/files/company_tickers.json",
        http_status=200, content_type="application/json", terms_note="SEC public data",
    )
    assert draft.sha256 == hashlib.sha256(b"{}").hexdigest()
    assert draft.path == Path("sec/identities/company_tickers/2026/09/13") / f"{draft.sha256}.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_raw_store.py -q`
Expected: FAIL because the raw storage module is absent.

- [ ] **Step 3: Implement write-once storage**

Write bytes with exclusive-create semantics, fsync the file, and return a draft containing hash, byte size, path, and metadata. A repeated response must not overwrite differing bytes at the same hash path. Persist the database reference only after the file exists; keep the raw row immutable.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_raw_store.py -q`
Expected: PASS, including duplicate replay and metadata tests.

- [ ] **Step 5: Commit**

```bash
git add src/fdc/raw_store.py src/fdc/provenance.py tests/unit/test_raw_store.py
git commit -m "feat: retain SEC raw responses"
```

### Task 4: Add SEC Client, Fixtures, and Normalizers

**Files:**
- Create: `src/fdc/providers/sec/client.py`
- Create: `src/fdc/providers/sec/schemas.py`
- Create: `src/fdc/providers/sec/normalize.py`
- Create: `tests/fixtures/sec/company_tickers.json`
- Create: `tests/fixtures/sec/submissions_cik_0000320193.json`
- Create: `tests/unit/test_sec_normalize.py`
- Create: `tests/unit/test_sec_client.py`

**Interfaces:**
- `SecClient.fetch_company_tickers() -> HttpResponsePayload`.
- `SecClient.fetch_submissions(cik: str) -> HttpResponsePayload`.
- `normalize_company_tickers(payload: Mapping[str, Any], fetched_at: datetime) -> list[IssuerCandidate]`.
- `normalize_submissions(payload: Mapping[str, Any], cik: str, fetched_at: datetime) -> list[SubmissionCandidate]`.

- [ ] **Step 1: Write failing parser tests**

```python
def test_submission_parallel_arrays_are_joined_by_index():
    records = normalize_submissions(load_fixture("submissions_cik_0000320193.json"), "0000320193", FETCHED_AT)
    assert records[0].accession_number == "0000320193-25-000001"
    assert records[0].filing_date == date(2025, 3, 1)

def test_mismatched_submission_arrays_fail_closed():
    payload = {"filings": {"recent": {"accessionNumber": ["a"], "form": []}}}
    with pytest.raises(SourceShapeError, match="parallel arrays"):
        normalize_submissions(payload, "0000320193", FETCHED_AT)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_sec_normalize.py -q`
Expected: FAIL because client schemas and normalizers are absent.

- [ ] **Step 3: Implement client and normalizers**

Use `httpx.Client` with the configured SEC user-agent, timeout, and rate-limit-aware retry classification. Parse CIK into ten digits, validate required source keys, preserve nullable source timestamps, and explicitly validate every SEC parallel-array length before zipping. Do not synthesize ticker validity windows from absent source facts; emit source timestamps as nullable candidates for the sync layer.

- [ ] **Step 4: Run parser/client tests**

Run: `pytest tests/unit/test_sec_client.py tests/unit/test_sec_normalize.py -q`
Expected: PASS using mocked HTTP responses and committed fixtures only.

- [ ] **Step 5: Commit**

```bash
git add src/fdc/providers tests/fixtures/sec tests/unit/test_sec_client.py tests/unit/test_sec_normalize.py
git commit -m "feat: parse SEC identity and submissions"
```

### Task 5: Build Idempotent, Checkpointed Sync Services

**Files:**
- Create: `src/fdc/sync/service.py`
- Create: `src/fdc/sync/retry.py`
- Create: `src/fdc/sync/__init__.py`
- Create: `tests/unit/test_sync_service.py`
- Create: `tests/integration/test_fixture_replay.py`

**Interfaces:**
- `SyncService.sync_sec_identities(scope: str) -> UUID`.
- `SyncService.sync_sec_submissions(cik: str) -> UUID`.
- `SyncService.retry_run(run_id: UUID) -> UUID`.
- `SyncService.get_run(run_id: UUID) -> ProviderRun`.
- `RetryPolicy.classify(exc: Exception) -> Literal["transient", "permanent"]` and `.delay(attempt: int) -> float`.

- [ ] **Step 1: Write failing workflow tests**

```python
def test_fixture_replay_is_idempotent(service, fixture_client):
    first_run = service.sync_sec_identities("fixture")
    second_run = service.sync_sec_identities("fixture")
    assert count_rows(Issuer) == 1
    assert count_rows(Instrument) == 1
    assert get_run(second_run).status == "completed"

def test_permanent_error_becomes_dead_letter(service, failing_client):
    run_id = service.sync_sec_submissions("0000320193")
    assert get_run(run_id).status == "dead_letter"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_sync_service.py -q`
Expected: FAIL because orchestration and retry policy are absent.

- [ ] **Step 3: Implement run lifecycle**

Create a run before network access. Store raw bytes before parsing. Upsert issuers by provider/CIK, create instruments only when a stable source identity supports it, and write ticker mappings without changing an existing instrument ID. Normalize submissions by accession number. Advance the checkpoint only after raw persistence, normalized transaction, and provenance linkage commit. Retry transient HTTP failures with exponential backoff; on permanent errors record structured details and mark `dead_letter`. Mark valid-but-incomplete scopes `partial` with a `Coverage` gap.

- [ ] **Step 4: Run replay and interruption tests**

Run: `pytest tests/unit/test_sync_service.py tests/integration/test_fixture_replay.py -q`
Expected: PASS, including second-run no-duplicate assertions and checkpoint resume.

- [ ] **Step 5: Commit**

```bash
git add src/fdc/sync tests/unit/test_sync_service.py tests/integration/test_fixture_replay.py
git commit -m "feat: add resumable SEC sync"
```

### Task 6: Expose the Operational CLI

**Files:**
- Create: `src/fdc/cli.py`
- Create: `tests/unit/test_cli.py`

**Interfaces:**
- Commands: `fdc sync sec-identities --scope <scope>`, `fdc sync sec-submissions --cik <cik>`, `fdc runs show <run_id>`, and `fdc runs retry <run_id>`.
- Each command returns exit code 0 only for `completed`; `partial`, `failed`, and `dead_letter` produce nonzero exit codes while printing the run ID and structured status.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_sync_command_prints_run_id_and_status(cli_runner, mocker):
    mocker.patch("fdc.cli.SyncService.sync_sec_identities", return_value=RUN_ID)
    result = cli_runner.invoke(app, ["sync", "sec-identities", "--scope", "fixture"])
    assert result.exit_code == 0
    assert str(RUN_ID) in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli.py -q`
Expected: FAIL because the Typer app is absent.

- [ ] **Step 3: Implement commands**

Keep CLI writes inside `SyncService`; render JSON for machine-readable run output and human-readable errors to stderr. Validate ten-digit CIK input and preserve the exact run status semantics from the schema.

- [ ] **Step 4: Run CLI tests**

Run: `pytest tests/unit/test_cli.py -q && fdc --help`
Expected: PASS and help lists all four command groups.

- [ ] **Step 5: Commit**

```bash
git add src/fdc/cli.py tests/unit/test_cli.py
git commit -m "feat: add collector CLI"
```

### Task 7: Add Read-Only API and `as_of` Queries

**Files:**
- Create: `src/fdc/read_service.py`
- Create: `src/fdc/api.py`
- Create: `tests/unit/test_read_service.py`
- Create: `tests/integration/test_api.py`

**Interfaces:**
- `search_instruments(session: Session, query: str, as_of: datetime | None) -> list[InstrumentView]`.
- `get_instrument(session: Session, instrument_id: UUID) -> InstrumentView`.
- `list_identifiers(session: Session, instrument_id: UUID, as_of: datetime | None) -> list[IdentifierView]`.
- `list_submissions(session: Session, issuer_id: UUID, as_of: datetime | None) -> list[SubmissionView]`.
- FastAPI app object `app` with routes `/v1/instruments`, `/v1/instruments/{instrument_id}`, `/v1/instruments/{instrument_id}/identifiers`, `/v1/issuers/{issuer_id}/submissions`, and `/v1/runs/{run_id}`.

- [ ] **Step 1: Write failing `as_of` tests**

```python
def test_submissions_as_of_excludes_future_disclosures(session, issuer):
    insert_submission(issuer, filing_date=date(2025, 3, 1), disclosed_at=dt("2025-03-01T15:00:00Z"))
    insert_submission(issuer, filing_date=date(2025, 2, 1), disclosed_at=dt("2025-02-01T15:00:00Z"))
    rows = list_submissions(session, issuer.id, as_of=dt("2025-02-28T23:59:59Z"))
    assert [row.filing_date for row in rows] == [date(2025, 2, 1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_read_service.py -q`
Expected: FAIL because read services and API routes are absent.

- [ ] **Step 3: Implement read services and routes**

Use parameterized SQLAlchemy queries. For `as_of`, filter on disclosure/effective time when present and exclude rows with a known future timestamp; never substitute fetch time for a missing disclosure time. Return explicit nullable fields, provider/run/raw references, and coverage limitations. Reject API methods that attempt POST/PUT/PATCH/DELETE by not registering them.

- [ ] **Step 4: Run API tests**

Run: `pytest tests/unit/test_read_service.py tests/integration/test_api.py -q`
Expected: PASS, including 404 handling and `as_of` behavior.

- [ ] **Step 5: Commit**

```bash
git add src/fdc/read_service.py src/fdc/api.py tests/unit/test_read_service.py tests/integration/test_api.py
git commit -m "feat: expose read-only collector API"
```

### Task 8: Add Acceptance Replay, Live Smoke Test, and Runbook

**Files:**
- Create: `scripts/live_sec_smoke.py`
- Create: `tests/acceptance/test_vertical_slice.py`
- Create: `docs/runbook.md`
- Modify: `README.md`

**Interfaces:**
- `scripts/live_sec_smoke.py` exits 0 only when `FDC_SEC_USER_AGENT` is set and the smallest SEC request returns valid JSON; it prints `fixture_tests` and `live_smoke` as separate statuses.
- `docs/runbook.md` documents local startup, migration, fixture replay, retry inspection, raw partition layout, and cloud migration assumptions.

- [ ] **Step 1: Write failing acceptance test**

```python
def test_vertical_slice_replay_has_traceable_provenance(replay_app):
    run_id = replay_app.sync("fixture")
    instrument = replay_app.find_instrument("AAPL")
    assert instrument.instrument_id
    assert instrument.raw_object_id
    assert instrument.provider_run_id == run_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/acceptance/test_vertical_slice.py -q`
Expected: FAIL until the API, sync service, and provenance joins are wired together.

- [ ] **Step 3: Implement smoke test and documentation**

Make the live smoke script opt-in and never run as part of deterministic CI. Document `docker compose up -d postgres`, `alembic upgrade head`, fixture replay, API startup, and the required SEC user-agent format. Add a coverage report that distinguishes provider coverage gaps from application failures.

- [ ] **Step 4: Run the full acceptance suite**

Run: `pytest -q --cov=fdc --cov-report=term-missing && python scripts/live_sec_smoke.py`
Expected: fixture/unit/integration tests PASS; live smoke reports `SKIPPED` when explicitly disabled or `PASS` with a configured SEC identity, never conflating the two.

- [ ] **Step 5: Commit**

```bash
git add scripts/live_sec_smoke.py tests/acceptance docs/runbook.md README.md
git commit -m "test: document vertical slice acceptance"
```

## Self-Review

- **Spec coverage:** Identity and issuer mapping are covered by Tasks 2 and 4-5; timestamp/as-of semantics by Task 7; provider policy and raw retention by Tasks 3-5; CLI/API split by Tasks 6-7; retries, checkpoints, partial/dead-letter states by Task 5; fixture replay and live smoke separation by Tasks 4, 5, and 8.
- **Placeholder scan:** No `TODO`, `TBD`, or unspecified implementation steps are used; each task names files, interfaces, tests, commands, and expected outcomes.
- **Type consistency:** `Settings`, model names, `RawObjectDraft`, `SecClient`, normalizer candidates, `SyncService`, read-service functions, and FastAPI `app` are defined before downstream tasks consume them.
- **Scope:** This remains one vertical slice. Prices, company actions, global providers, scheduling, cloud hosting, and API writes are explicitly excluded.

