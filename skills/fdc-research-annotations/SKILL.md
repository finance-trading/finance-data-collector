---
name: fdc-research-annotations
description: >
  Read and update a stock's research annotations in the Finance Data Collector
  service: position bands (observation/建仓 entry, add/补仓, reduce/减仓 price
  ranges) and the watch-items list (观察事项, each with a creation time). Use
  this skill whenever the user asks to look up or change entry/position
  prices, add-on or trim ranges, watch items, or research notes for a ticker
  on their FDC service — even when they say it casually ("把 NVDA 建仓区间改成
  120-140", "给 TSM 加个观察事项"), without naming the API. Can also filter
  the AI company directory (list companies by layer, segment, ingestion
  status, funnel tier, keyword; sorted by price/market-cap metrics).
---

# FDC research annotations

Read/update per-ticker research state through the open API of a Finance Data
Collector service:

- **Position bands** — four price ranges per company: `observation_range`
  (观察区间), `entry_range` (建仓), `add_range` (补仓), `reduce_range` (减仓).
  Bands are human research records, not trade authorizations — say so when
  reporting them.
- **Watch items** — an ordered (P1/P2/P3) list of things to keep an eye on.
  Each item may carry:
  - `code` — a short free-form classification tag (≤32 chars), e.g. `FIN`,
    `COMP`, `POL`, `财报`. Suggested tags: FIN / COMP / POL / PROD / VAL / OPS / MGR / MACRO.
  - `created_at` — server-stamped the moment the item was added; editing keeps it.
  - `next_check_at` — the next point at which the item deserves attention
    (a date or ISO datetime, chosen by the user).

- **Company directory filtering** — read-only `list` over the 211-company AI
  universe: filter by keyword, AI layer (repeatable), segment, ingestion
  status, funnel tier (1 core / 2 major / 3 watch); sort by `market_cap`,
  `change_pct`, `week_change_pct`, `week_rise_pct`, `change_52w_pct`,
  `rise_52w_pct`. No key needed; `--json` gives the full API view.

## Configuration

Two values drive everything. The script bundles working defaults (service
origin `http://127.0.0.1:8000` and the operator's API key) as Python
constants, so **reads and writes both work out of the box** — no setup.
Every value can be overridden:

| What | CLI flag | Env var | Bundled default |
| --- | --- | --- | --- |
| Service origin, e.g. `https://fdc.example.com` | `--base` | `FDC_API_BASE` | `http://127.0.0.1:8000` |
| API key (writes only; reads need none) | `--key` | `FDC_API_KEY` | the operator's key, in the script |

Resolution order: flag → environment variable → bundled constant in
`scripts/fdc_annotations.py`. If the service operator rotates the key, they
update the constant (and tell the user — a 401 means the bundled key is
stale).

## Working with the API

All commands go through the bundled script — stdlib only, no install step:

```bash
python3 <skill-base-dir>/scripts/fdc_annotations.py [--base URL] [--key KEY] <command>
```

(`<skill-base-dir>` is the directory containing this SKILL.md, printed as
"Base directory for this skill:" when the skill loads.)

| Intent | Command |
| --- | --- |
| See bands + watch items | `get NVDA` |
| Filter companies | `list --funnel-tier 1 --layer compute --limit 25` (`--query`, repeatable `--layer`, `--segment`, `--ingestion-status`, `--sort`, `--order`, `--offset`, `--json` also supported) |
| Set / change / clear bands | `set NVDA --entry 120 140 --add 100 110 --reduce null null` |
| List watch items | `watch NVDA list` |
| Add a watch item | `watch NVDA add "Track datacenter capex" --priority 1 --code FIN --next-check 2026-02-05` |
| Edit one item | `watch NVDA edit "Track capex" --new-text "Track datacenter capex" --priority 1 --code FIN` |
| Remove one item | `watch NVDA remove "Track capex"` |

Semantics that matter when interpreting or composing results:

- **Bands are partial updates.** `set NVDA --entry 120 140` touches only the
  entry band; the other three keep their stored values. Sending `null null`
  for a band clears it. The response is the company's full view after the
  write — report from it, not from what you sent.
- **Watch-item mutations replace the whole list**, so the script fetches the
  current list first, applies your change, and sends the full list back.
  Surviving items keep their `created_at`, `code`, and `next_check_at`; new
  items are stamped `created_at` server-side. If you ever hand-roll a POST
  instead of using the script, do the same fetch → mutate → replace dance or
  you will wipe out items you never touched.
- **Matching watch items is by exact text** (stripped). Ambiguous or missing
  text fails with the current list printed — show it to the user and let
  them pick.
- Read-only calls never need the key. If the user only asks to *look*
  something up, don't nag them for credentials.

## Errors and what they mean

The script exits non-zero with a one-line diagnosis; the mapping:

- `HTTP 401` — writes are key-gated and the key is missing or wrong. Confirm
  with the user whether `FDC_API_KEY` is set; do not print the key back.
- `HTTP 403` — the service is in local-only mode (operator never set a key).
  Telling the user to ask the operator to set `FDC_API_KEY` is the whole fix.
- `HTTP 404` (unknown ticker) — the ticker is not in the AI universe this
  service serves. Cross-check with `GET {base}/api/v1/companies?query=...` if
  the user is unsure of the spelling.
- `HTTP 422` — payload rejected; the message names the offending field
  (band ordering, blank or too-long item text, 50-item cap).

## Reporting

Keep it short: what changed (or what exists), the resulting band values as
`low–high`, and — when watch items are in play — the item count and, for new
items only, that the creation time was stamped now. For `get`, a compact
table: one line per band, then the P1/P2/P3 items with their `added` times.
