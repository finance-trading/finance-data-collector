# Company Quality Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate CQ_V2 quality scoring into this project, persist each calculated run as an immutable company snapshot with explanations, seed the latest source snapshot for catalog companies, and show each company’s latest score on its detail page.

**Architecture:** Copy and hash the annual-facts input into the project, port the needed CQ_V2 calculations into focused `fdc` modules, and use the complete source 480-company universe for peer ranks while persisting only catalog matches. Add a versioned SQLAlchemy table and transactional snapshot service, expose a latest-score API, and render it independently from the existing filing workspace.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, Pandas, NumPy, Pydantic, TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-quality-score-design.md`

## Global Constraints

- Database stores computed score results, explanations, and snapshot metadata only; it does not store annual source facts, peer-ranking intermediates, or rule definitions.
- Use the source snapshot’s full 480-company peer universe for sector ranks; persist only companies matched to this project’s `data/ai_companies.json` catalog.
- Initial imported rating cutoff is `2026-09-30`; source run is `cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4`; rule version is `CQ_V2`; semantic policy is `CQ_EDGARTOOLS_SEMANTIC_POLICY_V2`.
- Each run is a separate immutable snapshot; unique `(snapshot_id, ticker)`; repeated snapshot writes must not produce duplicate rows or partial snapshots.
- Missing data is unavailable/UNKNOWN as specified by the source model, never silently converted to score zero.
- No new runtime dependencies; use existing Pandas/NumPy.
- No runtime imports from the neighboring `finance-stastic` repository.
- No front-end dependency additions; use safe DOM text nodes and preserve accessible status messaging.

---

## File map

**Create**
- `data/company_quality/edgartools_annual_facts_2026-10-05.csv.gz` — compressed annual-facts input copied from the source project; tracked and accompanied by an input manifest/hash.
- `data/company_quality/cq_v2_source_snapshot.csv.gz` — optional checked-in compact source ratings fixture if needed for reproducible bootstrap/acceptance; must contain only computed ratings, not raw facts.
- `src/fdc/quality_score.py` — pure calculations: facts/window preparation, CQ_V2 dimension features, peer ranking, hard gates, explanation serialization.
- `src/fdc/quality_score_store.py` — transactional persistence and latest-snapshot reads.
- `alembic/versions/0010_company_quality_score.py` — table and indexes only; no seed records.
- `scripts/import_quality_snapshot.py` — explicit command to calculate/import a snapshot from checked-in facts with selectable snapshot id/cutoff and optional dry-run.
- `tests/unit/test_quality_score.py` — feature and ranking golden tests.
- `tests/unit/test_quality_score_store.py` — snapshot persistence/rollback/read tests.
- `tests/integration/test_api_quality_score.py` — API integration tests.
- `frontend/src/api/quality-score.ts` — quality-score response type and API loading function (only if it fits current API module conventions; otherwise use `types.ts` and `company.ts`).

**Modify**
- `src/fdc/models.py` — `CompanyQualityScore` SQLAlchemy model and constraints/indexes.
- `src/fdc/api.py` — `GET /api/v1/companies/{ticker}/quality-score` endpoint.
- `tests/unit/test_models.py` and/or `tests/integration/test_schema.py` — schema assertions and migration coverage following current conventions.
- `frontend/company.html` — semantic Quality Score panel placeholder.
- `frontend/src/pages/company.ts` — independent quality-score fetch/render, including no-record and error states.
- `frontend/tests/company.test.ts` — quality score rendering tests.
- `frontend/tests/build-contract.test.ts` — only if static page/build contract requires new IDs/assets.

## Task 1: Preserve source inputs and derive a small CQ_V2 golden fixture

**Files:**
- Create: `data/company_quality/edgartools_annual_facts_2026-10-05.csv.gz`
- Create: `data/company_quality/source_manifest.json`
- Create: `tests/fixtures/quality_score/cq_v2_source_sample.json`
- Create: `tests/unit/test_quality_score.py`

**Interfaces:**
- Fixture records include `ticker`, `cik`, `rating_cutoff`, `rule_version`, `semantic_policy`, `quality_score`, `score_available`, `status`, five dimension scores, `dimension_count`, `peer_count`, `v2_hard_status`, `v2_unknown_reasons`, and `unknown_reasons`.
- Sample at least one `QUALIFIED`, `NOT_QUALIFIED`, `UNKNOWN`, `SEPARATE_MODEL`, and score-unavailable row from source snapshot `../finance-stastic/data/company_quality/cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4/rating_snapshots.csv.gz`.

- [ ] **Step 1: Write failing source contract tests**

Add tests that load `tests/fixtures/quality_score/cq_v2_source_sample.json` and assert all five statuses are represented, all dimension fields exist, available scores are numeric, unavailable scores are null, and each row carries CQ_V2 + cutoff `2026-09-30`.

- [ ] **Step 2: Run the focused test and verify it fails because the fixture is absent**

Run: `pytest tests/unit/test_quality_score.py -q`
Expected: FAIL with fixture-not-found (tests are intentionally written before fixture generation).

- [ ] **Step 3: Copy exact source annual facts and generate the compact fixture**

Copy the source facts file to the path above without transforming bytes. Create `source_manifest.json` containing relative path, source filename, source run ID, SHA-256 of copied facts, SHA-256 of source `rating_snapshots.csv.gz`, cutoff, rule version, semantic policy, and peer universe source filename. Extract the named source sample rows into JSON; do not include the full source project path in runtime configuration.

- [ ] **Step 4: Verify hashes and fixture tests**

Run: `shasum -a 256 data/company_quality/edgartools_annual_facts_2026-10-05.csv.gz ../finance-stastic/data/company_quality/cq-edgartools-annual-facts-2026-10-05-v2/edgartools_annual_facts.csv.gz`
Expected: both hashes identical. Then run `pytest tests/unit/test_quality_score.py -q`; expected PASS.

- [ ] **Step 5: Commit source inputs and contract tests**

```bash
git add data/company_quality tests/fixtures/quality_score tests/unit/test_quality_score.py
git commit -m "test: add CQ v2 quality score source fixtures"
```

## Task 2: Port pure CQ_V2 scoring and peer ranking

**Files:**
- Create: `src/fdc/quality_score.py`
- Modify: `tests/unit/test_quality_score.py`

**Interfaces:**
- `calculate_quality_scores(facts: pandas.DataFrame, universe: pandas.DataFrame, rating_cutoff: date) -> pandas.DataFrame`
- `match_catalog_companies(scores: pandas.DataFrame, catalog: CatalogView) -> pandas.DataFrame`
- Both functions are pure: no DB, file I/O, API calls, or import from `finance-stastic`.

- [ ] **Step 1: Add failing golden comparison tests**

Implement tests loading the source facts file and universe source, calling `calculate_quality_scores`, then comparing the five chosen fixture companies on score/status/all dimension scores/hard-gate counts/reasons. Include assertions that missing facts remain null and source statuses match exactly.

- [ ] **Step 2: Run tests and confirm missing implementation failure**

Run: `pytest tests/unit/test_quality_score.py -q`
Expected: FAIL because `fdc.quality_score` is not present.

- [ ] **Step 3: Port only the production scoring path and exact helper dependencies**

Read and port logic from `../finance-stastic/scripts/build_company_quality_edgartools_dimension_scores.py`, `../finance-stastic/src/finance_stastic/company_quality_snapshot.py` (`rank_peer_metrics` and any required feature builder), and `../finance-stastic/src/finance_stastic/company_quality_v2.py` (`evaluate_v2_hard_gates`). Keep the five dimensions, peer minimum 10, sector key, rounding, status transitions, semantics and missing-value behavior identical to source. Add explicit input schema checks and reject duplicate/ambiguous CIK/ticker identity rather than guessing. Use Pandas/NumPy already declared in `pyproject.toml`.

- [ ] **Step 4: Verify golden output and peer universe behavior**

Run: `pytest tests/unit/test_quality_score.py -q`
Expected: PASS. Include a test where the 480-company full universe yields source peer score but the 234-company catalog subset would differ, proving ranking happens before persistence filtering.

- [ ] **Step 5: Commit pure scoring implementation**

```bash
git add src/fdc/quality_score.py tests/unit/test_quality_score.py
git commit -m "feat: port CQ v2 quality scoring"
```

## Task 3: Add snapshot table and migration

**Files:**
- Modify: `src/fdc/models.py`
- Create: `alembic/versions/0010_company_quality_score.py`
- Modify: `tests/unit/test_models.py`
- Modify: `tests/integration/test_schema.py`

**Interfaces:**
- `CompanyQualityScore` fields follow the exact field set in the approved spec: company identity; cutoff/calculated time/snapshot/rule/policy; total score/availability/status/counts/periods; five dimensions; quality and hard-gate reasons; gate counts and CQ_V2 numeric indicators; source input hash.
- Unique constraint: `(snapshot_id, ticker)`.
- Indexes: `(ticker, calculated_at)` and `snapshot_id`.

- [ ] **Step 1: Add failing ORM/schema tests**

Test decimal score round-trip, nullable unavailable score, JSON reason list round-trip, unique snapshot+ticker constraint, and index presence. Add migration test consistent with `test_schema.py` that migrates an empty SQLite DB to head and checks the new table/constraints.

- [ ] **Step 2: Run tests and verify they fail**

Run: `pytest tests/unit/test_models.py tests/integration/test_schema.py -q`
Expected: FAIL because model and migration are absent.

- [ ] **Step 3: Implement model and migration only**

Use SQLAlchemy `Numeric`, `Date`, existing `UtcDateTime`, `JSON`, `Uuid`, and stable naming conventions. Use portable JSON and constraints supported by current SQLite/PostgreSQL setup. The Alembic migration must create table/indexes only; never seed data in migration.

- [ ] **Step 4: Verify migration and history constraints**

Run: `pytest tests/unit/test_models.py tests/integration/test_schema.py -q`
Expected: PASS. Test two snapshot IDs for one ticker persist, while duplicate ticker within one snapshot fails.

- [ ] **Step 5: Commit schema**

```bash
git add src/fdc/models.py alembic/versions/0010_company_quality_score.py tests/unit/test_models.py tests/integration/test_schema.py
git commit -m "feat: add company quality score snapshots"
```

## Task 4: Implement atomic snapshot store and import/calculation CLI

**Files:**
- Create: `src/fdc/quality_score_store.py`
- Create: `scripts/import_quality_snapshot.py`
- Create: `tests/unit/test_quality_score_store.py`
- Modify: `src/fdc/quality_score.py` (only to expose result serialization needed by store)

**Interfaces:**
- `write_quality_snapshot(session: Session, records: Sequence[CompanyQualityScore], *, snapshot_id: str) -> int`: validates one snapshot ID, inserts all records inside caller transaction, rejects existing snapshot ID or duplicate ticker before commit; returns inserted count.
- `get_latest_quality_score(session: Session, ticker: str) -> CompanyQualityScore | None`.
- CLI accepts `--snapshot-id`, `--rating-cutoff`, `--dry-run`; reads checked-in facts and full universe, calculates rankings for all 480, filters persisted scores to catalog companies only, and writes one all-or-nothing snapshot.

- [ ] **Step 1: Write failing store and CLI contract tests**

Test successful insert, latest snapshot selection for ticker, distinct snapshot history, repeated snapshot rejection, duplicate ticker rejection, and simulated insert error rollback with zero rows left. Test dry-run calculates and validates counts but leaves DB empty.

- [ ] **Step 2: Run tests and verify missing store fails**

Run: `pytest tests/unit/test_quality_score_store.py -q`
Expected: FAIL because store/CLI functions do not exist.

- [ ] **Step 3: Implement transactional store**

Require the caller to pass an active SQLAlchemy session. Add records in one transaction (or use a nested transaction only if needed by existing session patterns); preflight conflicting snapshot ID and duplicate tickers; do not catch-and-ignore DB integrity errors. Latest lookup sorts by `calculated_at DESC`, then `rating_cutoff DESC`, then stable `snapshot_id DESC`.

- [ ] **Step 4: Implement explicit calculator/import CLI**

Read `data/company_quality/source_manifest.json` and verify SHA-256 before calculation. Validate source universe count and input columns, load catalog, calculate all peers, match catalog using canonical ticker plus CIK where available, report matched/unmatched companies, and persist under one `SessionLocal` transaction. Dry-run must not create records. Errors exit nonzero and leave DB unchanged. Snapshot ID defaults to a deterministic run ID with a new-run suffix only when explicitly requested; never overwrite an existing snapshot.

- [ ] **Step 5: Run tests and dry-run against checked-in input**

Run: `pytest tests/unit/test_quality_score_store.py tests/unit/test_quality_score.py -q`
Expected: PASS. Then `python scripts/import_quality_snapshot.py --snapshot-id cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4 --rating-cutoff 2026-09-30 --dry-run`.
Expected: source peer universe validated, reports directory matches and computed score statuses, writes zero DB rows.

- [ ] **Step 6: Commit persistence and CLI**

```bash
git add src/fdc/quality_score_store.py scripts/import_quality_snapshot.py tests/unit/test_quality_score_store.py src/fdc/quality_score.py
git commit -m "feat: persist quality score snapshots"
```

## Task 5: Add latest quality score API

**Files:**
- Modify: `src/fdc/api.py`
- Create: `tests/integration/test_api_quality_score.py`
- Modify: `src/fdc/quality_score_store.py` only if needed for read contract

**Interfaces:**
- `GET /api/v1/companies/{ticker}/quality-score`
- Response includes `ticker`, `cik`, `company_name`, `rating_cutoff`, `calculated_at`, `snapshot_id`, `rule_version`, `semantic_policy`, `quality_score`, `score_available`, `status`, dimensions, peer/dimension counts, `unknown_reasons`, hard-gate status/reasons/counts, and gate metrics.
- Normalize ticker uppercase; return 404 with stable detail if ticker is not in catalog or has no score row; do not confuse no-score with score 0.

- [ ] **Step 1: Add failing endpoint tests**

Cover available score, unavailable score with null `quality_score`, source status UNKNOWN, missing ticker, ticker case normalization, and response schema types. Seed DB rows using test session fixtures.

- [ ] **Step 2: Run API tests and verify missing endpoint failure**

Run: `pytest tests/integration/test_api_quality_score.py -q`
Expected: FAIL with 404/route missing.

- [ ] **Step 3: Add response model and endpoint**

Use Pydantic response schema and existing `SessionLocal`/FastAPI conventions. Verify ticker belongs to catalog before querying; distinguish unknown company from catalog company with no imported rating. Keep read operations side-effect free.

- [ ] **Step 4: Verify API tests**

Run: `pytest tests/integration/test_api_quality_score.py -q`
Expected: PASS.

- [ ] **Step 5: Commit endpoint**

```bash
git add src/fdc/api.py tests/integration/test_api_quality_score.py src/fdc/quality_score_store.py
git commit -m "feat: expose company quality score API"
```

## Task 6: Render score and explanations on company detail page

**Files:**
- Modify: `frontend/company.html`
- Modify: `frontend/src/pages/company.ts`
- Modify: `frontend/tests/company.test.ts`
- Modify: `frontend/src/api/types.ts` or create `frontend/src/api/quality-score.ts` according to current patterns.

**Interfaces:**
- `QualityScoreView` matches the API response exactly, with nullable numeric values and reason arrays.
- `loadQualityScore(ticker: string, signal?: AbortSignal): Promise<QualityScoreView>` fetches the new company endpoint.
- Independent render states: loading, score available, score unavailable/status explanation, no score record, fetch failure.

- [ ] **Step 1: Add failing frontend tests**

Test formatting/render for qualified score, unknown score/null score, separate-model status, dimension list, hard gate reasons, no-record 404, API failure, and safe rendering of hostile strings as text (never HTML).

- [ ] **Step 2: Run focused tests and verify they fail due to missing UI**

Run: `cd frontend && npm test -- --run tests/company.test.ts`
Expected: FAIL for absent quality panel/render behavior.

- [ ] **Step 3: Add semantic panel and independent fetch/render**

Add a labelled section to company.html. Fetch score independently from company/filing data so a missing score cannot fail the company page. Render numbers only when `score_available === true` and score is non-null; otherwise show status and reasons. Build nodes with `document.createElement` and `textContent`; include cutoff, rule version, and dimension labels. Use role=status for non-error informational states and role=alert for network failure.

- [ ] **Step 4: Verify front-end tests and production build**

Run: `cd frontend && npm test -- --run tests/company.test.ts && npm run build`
Expected: tests PASS and Vite production build succeeds.

- [ ] **Step 5: Commit UI**

```bash
git add frontend/company.html frontend/src/pages/company.ts frontend/src/api frontend/tests/company.test.ts
git commit -m "feat: show quality score on company page"
```

## Task 7: Seed initial CQ_V2 snapshot and run end-to-end verification

**Files:**
- Modify/create through generated database only: configured development DB (do not commit local DB data)
- Modify: `docs/superpowers/specs/2026-11-17-quality-score-design.md` only if implementation reveals a necessary contract correction.

- [ ] **Step 1: Run all backend tests and frontend tests**

Run: `pytest -q && cd frontend && npm test -- --run`
Expected: all tests pass; report any pre-existing failures separately.

- [ ] **Step 2: Apply database migration**

Run: `alembic upgrade head`
Expected: migration `0010` applies without modifying other tables or data.

- [ ] **Step 3: Perform import dry-run and compare full source results**

Run CLI dry-run. Compare every catalog-matched company to source snapshot by canonical ticker/CIK for total score, five dimensions, score availability, status, dimension/peer counts, gate state/counts, and reasons. Tolerate only numeric serialization precision explicitly documented (absolute difference <= 0.000001); all statuses/strings must match exactly. Fix discrepancies before writing.

- [ ] **Step 4: Import one initial snapshot**

Run: `python scripts/import_quality_snapshot.py --snapshot-id cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4 --rating-cutoff 2026-09-30`
Expected: one row per matched catalog ticker, no duplicates, persisted row count equals dry-run match count.

- [ ] **Step 5: Verify API response and UI using persisted data**

Run: `pytest tests/integration/test_api_quality_score.py -q`; use existing local app/browser acceptance setup to load `frontend/company.html?ticker=<fixture ticker>` for one available company and one unavailable company. Verify score, status, dimensions, reasons and dates render; verify a filing/API failure is independent of quality score request.

- [ ] **Step 6: Run complete verification and inspect worktree**

Run: `pytest -q && cd frontend && npm test -- --run && npm run build`; then `git status --short`.
Expected: all checks pass and only intended source changes remain; local imported DB is not staged.

- [ ] **Step 7: Commit remaining integration test/doc updates**

```bash
git add tests frontend docs/superpowers/specs/2026-11-17-quality-score-design.md
git commit -m "test: verify quality score snapshot integration"
```

---

## Plan self-review

- Spec coverage: independent table/history/fields → Task 3; calculation rules and full peer universe → Tasks 1–2; input provenance/hash and transactional import → Tasks 1 and 4; initial catalog-only snapshot → Task 7; latest API → Task 5; detail UI and failure isolation → Task 6; migration/tests/build → Tasks 3 and 7.
- Scope is one end-to-end feature with separately testable calculation, storage, API, and UI components; no independent subsystem requires a separate plan.
- Naming/type consistency: calculation returns DataFrame, catalog matching filters result rows, persistence accepts ORM records under snapshot id, API serializes latest row, frontend `QualityScoreView` mirrors the API.
- No placeholders remain; specific test commands and behavioral expectations are included.
