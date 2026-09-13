# SEC Identity and Submissions Vertical Slice

## Status

Approved design. This document defines the first vertical slice for
`finance-data-collector`.

## Goals

Build a local-first, auditable data path that connects SEC issuer identity,
stable security identity, ticker history, and SEC submission metadata. The
slice must expose both a read-only API and an operational CLI while keeping
all writes behind provider-controlled sync tasks.

The implementation is local-only in this phase. PostgreSQL is the normalized
store; raw provider responses are retained on the local filesystem. The
boundaries must remain portable to a later cloud deployment.

## Non-goals

- Daily OHLCV prices, company actions, fundamentals, or estimates.
- Global exchanges or securities without a SEC CIK.
- A hosted cloud service or a resident scheduler.
- Write access through the public API.
- Filling unavailable history with estimates or another source.

## Scope and source policy

The first provider is the SEC official API. `company_tickers.json` is the
discovery input. `data.sec.gov/submissions/CIK##########.json` is the source
for issuer metadata and submission history. Every provider response is
retained before normalization with source URL, provider, data domain, fetch
time, content hash, and terms/authorization notes.

The initial universe is US-listed company securities with a SEC CIK. ETFs,
funds, non-US issuers, and securities without a CIK are out of scope until a
separate provider policy is approved.

## Data model

### `issuer`

Stable internal issuer identifier, SEC CIK, legal name, and source metadata.
CIK is normalized to a ten-digit string and is unique within the SEC provider.

### `instrument`

Stable, never-reused `instrument_id` for a security. It references
`issuer_id` but is not derived from a ticker. The record includes instrument
type, exchange when known, lifecycle timestamps, and provenance.

### `instrument_identifier`

Time-bounded identifiers for ticker, exchange, and identifier type. A mapping
has `valid_from` and nullable `valid_to`; uniqueness rules prevent overlapping
active mappings for the same provider/exchange/ticker where the source says
they cannot coexist. Ticker changes and reuse create new mappings, never a new
meaning for an old `instrument_id`.

### `sec_submission`

Submission metadata keyed by SEC accession number and CIK. It stores form,
filing date, report period, acceptance/effective timestamps when supplied,
primary document, accession URL, and the raw-object reference. SEC parallel
arrays are normalized by index with validation of equal lengths.

### `provider_run`

One row per CLI sync run: provider, domain, requested scope, status
(`running`, `completed`, `partial`, `failed`, `dead_letter`), checkpoint,
attempt count, start/end times, and structured error details.

### `raw_object`

Immutable reference to a retained raw response. The path is partitioned by
provider, domain, identifier/scope, and fetch timestamp. The row stores URL,
HTTP status, content type, byte size, SHA-256, fetched-at, and terms note.

### `coverage`

Provider/domain coverage facts: start/end, known gaps, restrictions, and the
run that established the observation. Missing history remains explicit.

## Time and `as_of` semantics

Facts carry distinct event/market time, disclosure or effective time, and
fetch time when applicable. An `as_of` read returns only facts whose
disclosure/effective time was known by the requested instant; fetch time is
retained for provenance and debugging. If a source does not provide one of
these times, the field is null rather than inferred.

## Sync workflow and CLI

The CLI is the only write path in this slice:

```text
fdc sync sec-identities --scope all
fdc sync sec-submissions --cik 0000320193
fdc runs show <run_id>
fdc runs retry <run_id>
```

Each task creates a `provider_run`, stores the raw response before parsing,
normalizes within a transaction, and advances its checkpoint only after the
transaction and provenance record succeed. Re-running the same scope is
idempotent.

HTTP requests use error-aware exponential backoff and honor SEC rate limits.
Transient failures are retried at request level. A run can resume from its
last checkpoint. Permanent errors are classified and moved to
`dead_letter`; a run with a valid subset is `partial`, never silently
`completed`.

## Read-only API

The API exposes normalized data and provenance but does not mutate it:

```text
GET /v1/instruments?query=<text>
GET /v1/instruments/{instrument_id}
GET /v1/instruments/{instrument_id}/identifiers
GET /v1/issuers/{issuer_id}/submissions?as_of=<RFC3339>
GET /v1/runs/{run_id}
```

Responses include stable IDs, source/provider, raw-object reference where
appropriate, observed timestamps, coverage limitations, and the applied
`as_of` value. Unknown or unavailable values remain explicit null/Unavailable
states.

## Testing and acceptance

The primary test harness uses fixed SEC fixtures and replay, so parsing,
normalization, idempotency, ticker history, and `as_of` behavior are tested
offline and repeatably. A controlled live smoke test performs the smallest
SEC request needed to validate credentials/identity headers, connectivity,
rate-limit handling, and response shape; it is not the source of deterministic
unit-test results.

Acceptance requires:

1. Fixture replay works without network access and a second replay adds no
   duplicate normalized records.
2. Ticker changes/reuse preserve the stable `instrument_id` and produce
   correct validity windows.
3. `as_of` excludes filings not yet disclosed at the requested time.
4. An interrupted run resumes from checkpoint without reprocessing completed
   work.
5. Permanent failures are visible as dead-letter records; partial coverage is
   reported as partial with an explicit gap.
6. Every normalized SEC record can be traced to a retained raw object and
   provider run through the API or database.
7. The live smoke test is separately reported from fixture-test success.

