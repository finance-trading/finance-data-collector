# SDD ledger — plan: docs/superpowers/plans/2026-09-25-sec-filing-parsing-platform-plan.md

## Setup

- Workspace: `.superpowers/sdd/2026-09-25-sec-filing-parsing-platform-plan`
- Branch at setup: `feat/sec-filing-parser`
- Base observed before Task 1: `9fc5e93f7f9616ef3a98afc21e567666bd9ae866`
- Existing unrelated untracked files preserved: `download_all_sec.sh`, `web/_dbg_index.html`.
- Spec authority: `docs/superpowers/specs/2026-09-25-sec-filing-parsing-platform-design.md`.

## Pre-flight conflict scan

| Scope | Producer / consumer | Finding | Ruling |
|---|---|---|---|
| Task 1 → Task 2 | `fdc.db` engine/session and settings → SQLAlchemy models/migrations | Runtime interfaces are defined before schema consumers. | Proceed; Task 1 owns engine/session only, Task 2 owns metadata/models. |
| Task 1 → Task 6 | parser version/settings → parse identity/orchestration | `parser_version` must be stable and environment-configurable. | Use `Settings.parser_version` as the serving version; no hard-coded second source. |
| Task 2 → Task 6 | model tables/current parse constraint → atomic persistence | Parse service depends on versioned rows and current-pointer semantics. | Task 2 must expose constraints; Task 6 must use them transactionally. |
| Task 3 → Task 4 | `LocalFiling`/`ParserOutput` → EdgarTools adapter | Adapter consumes archive contract, not raw filesystem conventions. | Task 3 owns contract names; Task 4 may add fields only compatibly. |
| Task 3 → Task 5 | `LocalFiling`/`ParserOutput` → HTML parser | Both parser paths emit the same draft contract. | Keep parser-specific internals private; merge through `ParserOutput`. |
| Task 4 + Task 5 → Task 6 | fact/statement/section/table/evidence drafts → DB transaction | Both adapters must preserve source and diagnostics. | Task 6 owns merge/order and failure boundaries; adapters never write DB. |
| Task 6 → Task 7 | `ParseRun`, `FilingParse`, read-service query shape → CLI/API | API must expose current successful results and explicit failures. | Task 7 consumes model/query contracts; no API write path. |
| Task 7 → Task 8 | API routes → company page | Web page depends on stable read-only JSON, not parser internals. | Freeze routes in Task 7 before page implementation. |
| Task 1 self-consistency | runtime tests vs files/interfaces | Tests require settings/database helpers created by the task. | Clean. |
| Task 2 self-consistency | model tests vs migration files | Tests exercise unique accession/version/evidence constraints named by task. | Clean. |
| Task 3 self-consistency | fixture tests vs scanner/contract outputs | Fixtures provide indexed annual/quarterly packages and explicit gap case. | Clean. |
| Task 4 self-consistency | adapter tests vs fixture double and normalization signatures | Tests assert period/dimension behavior produced by adapter. | Clean; local EdgarTools API uncertainty is isolated to adapter. |
| Task 5 self-consistency | HTML/disclosure tests vs parser files | Tests assert section locators and typed debt table output. | Clean. |
| Task 6 self-consistency | idempotency tests vs parse APIs | Tests cover same identity skip, versioned rerun, and partial failure. | Clean. |
| Task 7 self-consistency | CLI/API tests vs command and read-service interfaces | Tests exercise force/forms propagation and evidence response. | Clean. |
| Task 8 self-consistency | page contract tests vs files/runbook | Tests match page mounts and API fetch paths. | Clean. |

## Rulings

- Ruling: Work continues on the existing `feat/sec-filing-parser` branch — the user selected subagent-driven execution, and the current branch is an isolated feature branch rather than `main`; this avoids creating a second worktree and keeps pre-existing unrelated files untouched — cost if wrong: task commits would need relocation to a different worktree.
- Ruling: SQLite is allowed only as a fixture/test backend while PostgreSQL remains the serving target — this preserves deterministic offline tests without weakening the production schema contract — cost if wrong: PostgreSQL-specific behavior may require an additional integration pass.
- Ruling: EdgarTools local-file API uncertainty is resolved inside Task 4 with a pinned-version probe and raw-XBRL fallback — this keeps the plan executable without making network access a hidden dependency — cost if wrong: Task 4 may need a scoped adapter revision.
- Ruling: `ParseRun` is the immutable attempt record, while `FilingParse` is the immutable deterministic result for one exact artifact/parser/module identity — a forced retry of an existing successful identity must execute and record its outcome on the new `ParseRun` without deleting children or replacing the result's originating `parse_run_id`; a failed forced retry remains explicit in the new run error summary and leaves the last successful current result intact — cost if wrong: consumers that require a separate row per byte-identical attempt will need a future `FilingParseAttempt` schema migration.
- Ruling: Final review supersedes the earlier byte-identical-attempt deferral — add an explicit attempt discriminator/new migration now so every retry keeps its `FilingParse`, child rows, diagnostics, and originating `ParseRun`; incremental matching still uses the artifact/parser/module identity while attempt number distinguishes audit history — cost if wrong: the schema and service become more complex than the original one-row-per-identity model.
- Ruling: Parser-module `success` means the local parser completed and preserved all scoped unavailable/unsupported row states; optional missing sections/statements or one malformed table do not make the whole filing unservable — cost if wrong: downstream consumers must inspect per-row status rather than treating module success as completeness.

## Task status

- Task 1: complete — implementation commit `546f6e9`; independent review PASS; runtime/config tests passed.
- Task 2: complete — schema/migration implementation reviewed PASS after provenance fixes; focused 22 passed/1 skipped, full 82 passed/1 skipped, ruff clean.
- Task 3: fix round 1/5 (6 addressed, 0 open; commit `62f9161`)
- Task 3: complete — implementation commit `35443df`, hardening commit `62f9161`; scoped re-review APPROVED; 60 focused tests passed and Task 3 lint was clean.
- Task 4: fix round 1/5 (8 addressed, 2 open; commits `54b9897` and `51b600b`)
- Task 4: fix round 2/5 (2 addressed, 0 open; commit `2084265`)
- Task 4: complete — implementation commits `8aa8a7b` and `b6b6daf`; two scoped fix rounds PASS; focused adapter suite 42 passed/1 skipped, full deterministic suite 186 passed/2 skipped, Ruff clean.
- Task 5: fix round 1/5 (5 addressed, 1 open; commit `7242453`)
- Task 5: fix round 2/5 (1 addressed, 0 open; commit `2bf4fd9`)
- Task 5: complete — implementation commit `05c5b35`; two scoped fix rounds approved; focused suite 23 passed, full deterministic suite 209 passed/2 skipped, Ruff clean.
- Task 6: fix round 1/5 (3 addressed, 1 open; commit `3f94138`)
- Task 6: fix round 2/5 (1 addressed, 0 open; commit `f2cf9d9`)
- Task 6: minor (deferred): non-forced failed parses still aggregate parent-run counts/checkpoint in sync's follow-up transaction rather than the filing-failure transaction; final review must triage crash-boundary durability.
- Task 6: complete — implementation commit `5650790`; two scoped fix rounds approved; focused suite 14 passed, full deterministic suite 223 passed/2 skipped, Ruff clean.
- Task 7: fix round 1/5 (5 addressed, 0 open; commit `fd148b2`)
- Task 7: complete — implementation commit `64b2ec1`; scoped re-review PASS; focused suite 22 passed with pristine output, full deterministic suite 245 passed/2 skipped, Ruff clean, import-safe app exposes 13 total routes.
- Task 8: fix round 1/5 (6 addressed, 1 evidence-acceptance gap open; commit `5e32fa7`)
- Task 8: fix round 2/5 (1 addressed, 0 open; commit `a033145`)
- Task 8: complete — implementation commits `3ae24e7` and `edf5a4c`; two scoped fix rounds accepted; focused 11 passed, full deterministic suite 256 passed/2 skipped, Ruff/compileall/JS syntax clean, PostgreSQL migration PASS, live SEC SKIPPED without an operator contact identity.

## Final review

- Final whole-branch review: CHANGES REQUIRED (8 findings).
- Final fix wave: commit `cabe4f6`; 7 findings addressed.
- Final scoped re-review residual: Important — Decimal unary sign/inline scale arithmetic still uses the default 28-digit Decimal context and can round values above 28 significant digits.
- Ruling: the Decimal residual is real and load-bearing for evidence-grade numeric fidelity; do not present the branch as merge-ready. The SDD final-review breaker permits only one final fix wave, so surface this residual to the user for an explicit follow-up cycle — cost if wrong: extremely large/high-precision XBRL values can be silently changed before storage.
- Final scoped re-review residuals (non-blocking for current single-worker/local scope): PostgreSQL round-trip was skipped without `FDC_TEST_POSTGRES_URL`; live SEC was skipped without opt-in/contact identity; concurrent attempt-number allocation needs locking or unique-conflict retry before parallel workers.
- Follow-up precision cycle: complete — added failing >28-significant-digit regressions for inline scale, `sign="-"`, and parenthesized negatives; replaced default-context unary/multiplicative Decimal operations with exact tuple/copy operations; focused adapter 46 passed/1 skipped, full deterministic suite 268 passed/3 skipped, scoped Ruff/compileall/JS syntax clean. The release-blocking Decimal residual is resolved.
