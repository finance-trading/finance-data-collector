# Plan — Company directory: latest price + daily % change, refreshed once per day

Authority: user request "companies 列表需要展示最近股票价格和涨跌幅，每日一次更新" (display the
company list with the most recent stock price and % change, updated once per day). Chosen scheduler:
**cron** (user's decision). No formal spec file; this plan is the argument.

## Context

- The "companies list" is the AI company directory served by `GET /api/v1/companies`
  (`src/fdc/api.py:39`), built by `catalog.list_companies` (`src/fdc/catalog.py`) and rendered by
  `frontend/src/pages/directory.ts` + `frontend/index.html`.
- Universe: 227 tickers in `data/ai_companies.json`, all plain US tickers (verified: no dots/digits).
- `yfinance>=1.7` is already a dependency (pyproject). Reuse it — no new dependency.
- Existing generated-artifact pattern: `fdc.graph` and `fdc.ai_layers` write
  `data/generated/*.json` and the read API serves them. Follow it: a `fdc.quotes` module writes
  `data/generated/quotes.json`, catalog reads it back.
- Working branch: `feat/sec-filing-parser` (a feature branch, not main). SDD runs in place; no
  new worktree (the working tree already carries many uncommitted files the user owns).

## Global Constraints

- No new third-party dependency (yfinance is already present).
- Read side must degrade gracefully: if `quotes.json` is absent/stale, the API returns the
  directory with `price`/`change_pct` null — never a 500.
- Price + % change are the **last close** vs **previous close** of the last 5 trading days
  (Yahoo). Rounding: price 2dp, change_pct 2dp.
- % change sign: `+` prefix for positive, signed format for negative, `0.00%` when zero.
- Cron refresh runs **weekdays only** (Sat/Sun closes are stale) and the module is idempotent —
  it skips the network when `quotes.json` is already from today.
- Backend: ruff clean. Frontend: existing `frontend/tests/directory.test.ts` must stay green
  (it builds `CompanyDirectoryItem` literals — new fields are optional with defaults, so literals
  remain valid; add a render assertion for the price column).

## Tasks

### Task 1 — Quotes generator module `src/fdc/quotes.py` (DONE by controller, pre-dispatch)
- `QUOTES_PATH` constant added to `src/fdc/data_files.py` (DONE).
- `fdc.quotes`: `_load_tickers`, `fetch_quotes` (batched `yf.download` 5d daily closes),
  `write_quotes(force)` with today-skip, `main()` with `--force`. Run as `python -m fdc.quotes`.
- Status: implemented. Needs a network run + review.

### Task 2 — Read-side merge into catalog + API types
- `catalog._load_quotes()` reads `data/generated/quotes.json` (absent → empty, never raise).
- `CompanyDirectoryItem` gains `price: float | None`, `change_pct: float | None`,
  `quote_as_of: date | None` (default None → existing test literals stay valid).
- `list_companies` merges quotes keyed by `ticker.upper()`.
- Frontend `types.ts` `CompanyDirectoryItem` gains the three fields.
- Backend test: a unit test proving absent quotes file → null fields, and present file → fields set.

### Task 3 — Frontend price column + HTML
- `directory.ts` `renderCompanies`: price + % change cell (currency USD, up/down/flat classes).
- `frontend/index.html`: add `<th>Price</th>`, loading-row colspan 6 → 7.
- CSS: `.price-cell`, `.price-value`, `.price-change.up/.down/.flat` in `frontend/src/styles/index.css`
  (match existing dark-theme tokens).
- Extend `frontend/tests/directory.test.ts` with a price-render assertion.

### Task 4 — Cron scheduling (user's choice)
- One-line crontab: weekdays after market close, `cd <repo> && /Users/olijve/.local/bin/uv run python -m fdc.quotes`.
- `uv run` is preferred over the venv python so deps stay resolved. No log rotation needed for v1.

## Interfaces (for subagents)

- `data/generated/quotes.json` shape:
  ```json
  {"generated_at": "<iso-8601 UTC>", "source": "yfinance",
   "quotes": {"NVDA": {"price": 140.10, "previous_close": 138.50, "change_pct": 1.15}}}
  ```
- `catalog._load_quotes() -> tuple[dict[str, dict[str, float | None]], date | None]`
  (second element is `generated_at[:10]` as a `date`, else None).
- `CompanyDirectoryItem.price / .change_pct` are `float | None`; `.quote_as_of` is `date | None`.

## Pre-flight conflict scan

| # | Pair / check | What one produces vs. consumes | Finding | Ruling |
|---|---|---|---|---|
| 1 | Task 1 ↔ Task 2 | quotes.json file ↔ catalog reader | shapes agree (Interface above) | clean |
| 2 | Task 2 ↔ Task 3 | API item fields ↔ frontend types | both add the same 3 fields; TS types are non-optional-but-nullable, matching pydantic `x \| None` | clean |
| 3 | Task 2 vs `directory.test.ts` | new model fields vs test literals | fields default to None → existing literals stay valid (Pydantic/TS both tolerate) | clean — no test change required for validity; Task 3 adds one assertion |
| 4 | colspan | `index.html` loading-row `colspan="6"` vs 7 columns after Task 3 | must bump to 7 | task 3 owns it — noted, not a defect |
| 5 | plan-mandated "no new dep" vs review rubric | n/a | yfinance already present; constraint satisfiable | clean |

Scan is clean. Proceeding.
