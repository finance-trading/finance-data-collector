# Final Fix Wave Report

Date: 2026-09-26
Scope: final-review fixes for the SEC filing parser and research Web branch
Method: strict test-first changes; no Git command or commit was run in this wave.

## Outcome

All eight final-review findings are fixed. The checked-in miniature MSFT archive now
passes through the real scanner, real EdgarTools/raw-XBRL adapter, real HTML parser,
database current-result selection, and FastAPI read path without mocks. Optional or
malformed row states remain explicit but no longer make otherwise usable filings or
table collections unservable.

## Finding map

### Critical 1: row-scoped parser states blocked current results

- `src/fdc/parsers/html_parser.py` now reports module success after a readable local
  document was deterministically inspected. Missing optional sections and
  malformed/unsupported tables remain persisted with their row status and scoped
  diagnostics.
- `src/fdc/parsers/edgartools_adapter.py` now treats missing optional statements,
  fallback operation, and fact/statement availability asymmetrically: any usable
  facts or statements make the local module successful; zero usable standard output
  remains failed.
- `tests/unit/test_html_parser.py` and
  `tests/unit/test_edgartools_adapter.py` cover missing sections/statements,
  unsupported tables, malformed tables, fallback, and a fact-collection error with
  usable statements.
- `tests/integration/test_archive_to_api.py` proves the unmocked checked-in archive
  produces two successful current results and serves filing/fact API responses.

### Critical 2: one bad table rejected the whole collection

- `src/fdc/read_service.py` returns parsed tables with aggregate `status="partial"`
  and per-table diagnostic entries (including `table_id`, row status, and scoped
  diagnostics). Failed/unavailable rows are not presented as usable rows.
- HTTP 422/409 is returned only when the requested collection has no parsed table;
  failure wins over unavailable when both are present.
- `tests/integration/test_api_filings.py` covers mixed parsed+failed,
  parsed+unavailable, only-failed, and only-unavailable collections.

### Important 3: retries rewrote one deterministic result

- `src/fdc/models.py` adds `FilingParse.attempt_number`; identity uniqueness is now
  artifact/parser/module identity plus attempt number.
- `alembic/versions/0002_attempts_and_decimal_precision.py` adds the discriminator
  as a new migration and replaces the old unique constraint without changing 0001.
- `src/fdc/parsers/service.py` always creates a new result for an executed retry;
  prior FilingParse rows, child facts/sections/tables, evidence, diagnostics, and
  originating ParseRun IDs remain immutable. Incremental lookup still matches the
  deterministic identity and reuses/reactivates an existing success when no parse is
  executed.
- `tests/unit/test_models.py` verifies numbered-attempt uniqueness.
- `tests/integration/test_incremental_parse.py` verifies forced success and failure
  preserve old attempts and children while switching/retaining current correctly.

### Important 4: binary float and scale-6 loss

- `src/fdc/contracts.py` and `src/fdc/parsers/edgartools_adapter.py` use `Decimal`
  throughout numeric normalization, raw XBRL scale/sign processing, fact identity,
  and statement drafts.
- `src/fdc/models.py` uses `ExactNumeric`: PostgreSQL `NUMERIC(100,30)` and a
  text-backed SQLite test representation, avoiding SQLite driver's float coercion.
- Migration 0002 widens both fact and statement numeric columns.
- `src/fdc/read_service.py` serializes exact decimal strings and removes only
  storage-added trailing zeroes. `web/company.js` already renders the API string
  directly; numeric coercion is limited to non-authoritative chart-bar magnitude.
- Tests preserve and return `9007199254740993.125` exactly through adapter,
  persistence, and API.

### Important 5: persisted EDGAR URLs were absent

- `src/fdc/parsers/service.py` derives canonical archive URLs from normalized CIK,
  dashless accession, and primary/artifact filename.
- New filings receive the primary-document `Filing.sec_url`; each evidence row gets
  an artifact URL unless the parser supplied a more specific URL.
- Retries backfill a missing URL on an existing filing.
- `tests/unit/test_parse_service.py` asserts new-row and retry persistence, and the
  unmocked archive-to-API test asserts source URLs are served.

### Important 6: offline settings required an SEC identity

- `src/fdc/config.py` permits offline construction with no
  `FDC_SEC_USER_AGENT` and exposes `Settings.require_sec_user_agent()` for live SEC
  call sites.
- `tests/unit/test_config.py` covers offline success and network-identity rejection.
- The live smoke script remains opt-in and independently requires the monitored
  contact identity before a request.

### Minor 7: parent counts/checkpoint were separate and double-countable

- `src/fdc/parsers/service.py` commits the FilingParse outcome and parent-run
  success/failure count, checkpoint, and diagnostic disposition in the same
  transaction.
- `src/fdc/sync.py` no longer performs a second per-filing count/checkpoint commit;
  it only continues after the service signals an already-durable failed attempt.
- Existing crash-boundary coverage and forced retry tests verify durable failure,
  exact counts, and continued processing.

### Minor 8: EdgarTools changes did not affect identity

- `pyproject.toml` and `uv.lock` pin `edgartools==5.58.0` exactly.
- `src/fdc/parsers/service.py` includes the installed EdgarTools version in the
  parser-module manifest and therefore in `parser_modules_hash`.
- `tests/unit/test_parse_service.py` verifies the tested version is part of the
  manifest.

## RED evidence

The first combined targeted run failed for the intended missing behavior:

```text
29 failed, 84 passed, 1 skipped in 2.72s
```

Failures included offline Settings validation, HTML/EdgarTools partial status,
missing `attempt_number`, URL absence, missing EdgarTools manifest identity, large
decimal rounding to `9007199254740994.000000`, mixed-table 409/422 responses, and
the unmocked offline pipeline being blocked by User-Agent validation.

A separate regression test for retry URL backfill was also observed red:

```text
FAILED test_retry_backfills_missing_canonical_filing_url
AssertionError: assert None == canonical primary-document URL
1 failed in 0.12s
```

## GREEN and verification evidence

Final focused parser/storage/API suite:

```text
114 passed, 2 skipped in 2.26s
```

The skips were the separately opt-in large local archive integration and the
PostgreSQL round trip when `FDC_TEST_POSTGRES_URL` is absent. The required miniature
archive -> real parse -> current -> API test passed in this run.

Full deterministic suite:

```text
265 passed, 3 skipped in 6.07s
```

Migration suite (upgrade head, idempotent upgrade, downgrade base, metadata match):

```text
5 passed, 1 skipped in 0.29s
SKIPPED: FDC_TEST_POSTGRES_URL is not configured
```

Static validation:

```text
ruff: All checks passed!
compileall src tests alembic: PASS
node --check web/company.js: PASS
```

## Browser and API evidence

- Real Playwright/uvicorn acceptance suite: `9 passed in 4.22s`.
- It includes the 1280x800 company flow, filing switching, statement/fact/table and
  direct evidence endpoint behavior, stale-response protection, explicit API error
  states, and the 390x844 narrow responsive statement view.
- This is Web responsive QA only; no native mobile claim is made.
- Unmocked local archive-to-API test serves a successful current filing, facts, and
  canonical evidence URLs through the ASGI application.

## Live SEC and PostgreSQL state

Live SEC was intentionally not called because no monitored contact identity and
explicit opt-in were supplied:

```text
SKIPPED: set FDC_RUN_LIVE_SEC_SMOKE=1 to allow one attributed SEC request
```

A PostgreSQL migration+real parse+read API test now exists in
`tests/integration/test_archive_to_api.py`, and the schema migration test remains in
`tests/integration/test_schema.py`. Both are gated on `FDC_TEST_POSTGRES_URL`. The
environment did not provide it, so PostgreSQL execution is honestly reported as
SKIPPED rather than inferred from SQLite.

## Files changed

- `pyproject.toml`, `uv.lock`
- `alembic/versions/0002_attempts_and_decimal_precision.py`
- `src/fdc/config.py`, `src/fdc/contracts.py`, `src/fdc/models.py`
- `src/fdc/parsers/edgartools_adapter.py`
- `src/fdc/parsers/html_parser.py`
- `src/fdc/parsers/service.py`
- `src/fdc/read_service.py`, `src/fdc/sync.py`
- `tests/unit/test_config.py`
- `tests/unit/test_edgartools_adapter.py`
- `tests/unit/test_html_parser.py`
- `tests/unit/test_models.py`
- `tests/unit/test_parse_service.py`
- `tests/integration/test_api_filings.py`
- `tests/integration/test_incremental_parse.py`
- `tests/integration/test_archive_to_api.py`

Unrelated `download_all_sec.sh` and `web/_dbg_index.html` were not modified.

## Residual concerns

1. PostgreSQL-specific migration, exact NUMERIC round trip, parse, and API read are
   implemented but not executed here because `FDC_TEST_POSTGRES_URL` is unavailable.
2. Live SEC remains deliberately unverified without both explicit opt-in and a real
   monitored contact identity.
3. Attempt numbering is protected by the database unique constraint. If concurrent
   workers are later introduced for the same filing identity, callers should add a
   retry on a unique-conflict or allocate attempts under a database lock.

## Follow-up precision cycle

The scoped re-review found that Decimal unary negation and inline scale arithmetic
still used Python's default 28-significant-digit context. A bounded follow-up cycle
added real raw-inline-XBRL regressions above 28 significant digits for positive
scale, `sign="-"`, and parenthesized negatives. All three first failed with rounded
values, including the scaled result changing from
`1234567890123456789012345678912.34500` to
`1.234567890123456789012345679E+30`.

The adapter now changes Decimal sign with context-free copy operations and applies
inline scale by exact coefficient/exponent manipulation. Verification after the fix:

```text
focused regression: 3 passed
adapter suite: 46 passed, 1 skipped
full deterministic suite: 268 passed, 3 skipped
scoped Ruff, compileall, and JavaScript syntax: PASS
```

The prior release-blocking Decimal precision residual is resolved. PostgreSQL and
live-SEC execution remain explicitly skipped under the environment gates documented
above; the future concurrent attempt-allocation concern remains non-blocking for the
current single-worker scope.
