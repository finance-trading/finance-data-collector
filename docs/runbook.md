# SEC filing parser runbook

This runbook starts the PostgreSQL-backed parser, parses packages already in
the local SEC archive, and serves the read API and company research page from
one local origin.

## 1. Install the project

The supported runtime is Python 3.12 or newer. From the repository root:

```bash
uv sync
```

The examples below use `uv run`. An activated `.venv` is equivalent.

## 2. Start PostgreSQL and migrate the schema

```bash
docker compose up -d postgres
export FDC_DATABASE_URL='postgresql+psycopg://fdc:fdc@localhost:5432/fdc'
alembic upgrade head
```

`docker compose ps postgres` should report the service as healthy before a
large parse. Alembic reads `FDC_DATABASE_URL`; credentials are not stored in
`alembic.ini`.

## 3. Prepare the local SEC archive

Parsing is local-only. It does not download filings. Set `FDC_SEC_ROOT` to a
directory containing the downloader's indexed filing packages:

```text
sec/
  MSFT/
    filings_index.json
    10-K/
      0000950170-24-087843/
        msft-20240630.htm
        ...supporting filing artifacts
```

`filings_index.json` must identify the accession, form, filing date, report
date, and primary document. The package files referenced by the index must be
readable. The scanner accepts supported 10-K and 10-Q packages, records gaps,
and classifies artifacts by content. Images are not parser inputs.

```bash
export FDC_SEC_ROOT="$PWD/sec"
export FDC_PARSER_VERSION='filing-parser-v1'
```

Use the SEC downloader workflow separately when packages are missing. A live
download requires an identifying user agent, for example:

```bash
export FDC_SEC_USER_AGENT='Collector name@example.com'
```

Setting this variable does not make `fdc parse` download anything. Keep live
download success separate from local parse success.

## 4. Parse filings

Parse all supported packages for one ticker:

```bash
uv run fdc parse filings --ticker MSFT
```

Limit the run to selected forms or parse one local accession:

```bash
uv run fdc parse filings --ticker MSFT --forms 10-K,10-Q
uv run fdc parse filing --accession 0000950170-24-087843
```

The command prints the immutable run ID, status, input/success/failure counts,
checkpoint accession, and accession-scoped diagnostics. A partial or failed
run exits nonzero. Inspect a stored run with:

```bash
uv run fdc parse-runs show <run-id>
```

### Forced and versioned reparses

The normal command skips an artifact/parser/module identity that already has
a successful result. `--force` executes it again and records the attempt while
preserving the last successful current result if the retry fails:

```bash
uv run fdc parse filings --ticker MSFT --force
```

A parser-version change creates a distinct result identity. Set the serving
version consistently for both parsing and API reads:

```bash
uv run fdc parse filings \
  --ticker MSFT \
  --parser-version filing-parser-v2
export FDC_PARSER_VERSION='filing-parser-v2'
```

## 5. Start the API and research page

The FastAPI application mounts `web/` after its read-only API routes, so the
page and JSON API share one origin:

```bash
export FDC_DATABASE_URL='postgresql+psycopg://fdc:fdc@localhost:5432/fdc'
export FDC_SEC_USER_AGENT='Collector name@example.com'
export FDC_PARSER_VERSION='filing-parser-v1'
uv run uvicorn fdc.api:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/company.html?ticker=MSFT
```

The browser uses only `/api/v1` read routes. It does not calculate financial
metrics. `Unavailable`, `Unsupported`, and `Parse failed` remain visible rather
than being converted to zero. Interactive API documentation is available at
`http://127.0.0.1:8000/docs`.

For static-only inspection, `python -m http.server -d web 8001` can render the
page shell, but API-backed content will not load. Use the FastAPI command for a
functional research page.

## 6. Deterministic checks

The default suite uses local fixtures and SQLite. It does not require a live
SEC request or PostgreSQL:

```bash
uv run pytest tests/acceptance/test_company_page.py -q
uv run pytest -q
uv run ruff check src tests
uv run python -m compileall src
```

The checked-in MSFT fixture archive is under `tests/fixtures/filings/MSFT`.
Parser adapter fixtures are under `tests/fixtures/edgar`.

## 7. Optional integration and live checks

Report each optional check separately; do not treat a skip as fixture-test
success.

```bash
docker compose up -d postgres
alembic upgrade head
python scripts/live_sec_smoke.py
```

The PostgreSQL result is `PASS` only after the container is healthy and the
migration succeeds. The live command above is safe by default and reports
`SKIPPED` without making a request. To allow its single read of the public SEC
company-ticker file, opt in explicitly and provide a monitored contact email:

```bash
FDC_RUN_LIVE_SEC_SMOKE=1 \
FDC_SEC_USER_AGENT='Finance Data Collector your-real-email@your-domain.com' \
  python scripts/live_sec_smoke.py
```

Do not use the placeholder address literally. The live result is `PASS` only
when the attributed request succeeds and the returned JSON contains the
expected MSFT record. Missing opt-in or contact configuration is `SKIPPED`;
network, HTTP, or payload validation errors are `FAILED` with a nonzero exit.
Report this separately from PostgreSQL and fixture tests. A missing local
filing package is not permission to download during a parse run.

## 8. Stop local services

Stop the API with `Ctrl-C`. Stop PostgreSQL without deleting its volume:

```bash
docker compose stop postgres
```

Use `docker compose down` only when removing the project network is intended.
Do not add `-v` unless deleting the local PostgreSQL data is explicitly wanted.
