# FDC research-annotation API reference

Base: the service origin (env `FDC_API_BASE`). All paths JSON, UTF-8.

## Endpoints

### GET /api/v1/research/annotations/{ticker} — open, no credential

One company's saved position bands and watch items.

200 response:

```json
{
  "ticker": "NVDA",
  "observation_range": {"low": null, "high": null},
  "entry_range": {"low": 120.0, "high": 140.0},
  "add_range": {"low": null, "high": null},
  "reduce_range": {"low": 250.0, "high": 270.0},
  "intrinsic_value": 307.84,
  "scen_bear": 225.24,
  "scen_base": 304.84,
  "scen_bull": 396.46,
  "watch_items": [
    {"priority": 1, "text": "Track datacenter capex",
     "code": "FIN",
     "created_at": "2026-11-03T08:14:02.735496+00:00",
     "updated_at": "2026-11-06T09:30:12.100200+00:00",
     "next_check_at": "2026-11-20"}
  ],
  "annotation_saved": true
}
```

- `intrinsic_value` and `scen_bear`/`scen_base`/`scen_bull` are model-derived
  forward values per share (USD) — a research cross-check, **not** a confirmed
  price. All four are `null` when no valuation batch has been saved for the
  company.

- `watch_items` fall back to the tier defaults for companies that have never
  been saved (`annotation_saved: false`); defaults carry `created_at` too.
- `code` is a free-form classification tag (≤32 chars), `null` when unset.
- `next_check_at` is the next point the item deserves attention
  (ISO date or datetime), `null` when unset.
- `created_at` is `null` on legacy items written before the field existed.
- `updated_at` is the server-stamped last-change time; `null` on items whose
  first save predates the field.
- `404` — ticker not in the served AI universe (ticker is matched case-insensitively).

### POST /api/v1/research/annotations/{ticker} — partial update

Body: any subset of

| field | shape | notes |
| --- | --- | --- |
| `observation_range`, `entry_range`, `add_range`, `reduce_range` | `{"low": float\|null, "high": float\|null}` | both null = clear the band; prices > 0, low ≤ high |
| `intrinsic_value`, `scen_bear`, `scen_base`, `scen_bull` | `float` (> 0) | model-derived forward value / three scenario prices per share (USD); research cross-check, not a confirmed price |
| `watch_items` | `[{priority: 1\|2\|3, text: 1–500 chars, code?: ≤32 chars, created_at?: iso8601, updated_at?: iso8601 (ignored), next_check_at?: iso date/datetime}]`, max 50 | **replaces the full list**; items sent back with their `created_at` keep it, items without get it stamped server-side; `updated_at` is always re-stamped server-side on save (client value ignored); `code`/`next_check_at` omitted = `null` |

Unsent fields are untouched. Response is the full post-write view (same shape
as GET). A company with no saved annotation is created on first write; its
default watch items are seeded from its funnel tier before your list applies.

Auth: local same-origin UI callers write without a credential; every other
caller needs `Authorization: Bearer $FDC_API_KEY`. Without a key configured
server-side, non-local writes get `401`/`403`.

| status | meaning |
| --- | --- |
| 401 | remote write, no/invalid key |
| 403 | local-only mode (server has no key) or cross-origin local write |
| 404 | ticker not in the universe |
| 422 | validation error — band endpoints incomplete, low > high, negative prices, blank/too-long item text, priority outside 1–3, more than 50 items |

## Examples

```bash
# Read (no credential)
curl "$FDC_API_BASE/api/v1/research/annotations/NVDA"

# Update one band
curl -X POST "$FDC_API_BASE/api/v1/research/annotations/NVDA" \
  -H "Authorization: Bearer $FDC_API_KEY" -H "Content-Type: application/json" \
  -d '{"entry_range": {"low": 120, "high": 140}}'

# Clear a band
-d '{"reduce_range": {"low": null, "high": null}}'

# Replace the whole watch list, keeping one item's creation time
-d '{"watch_items": [
      {"priority": 1, "text": "Track datacenter capex",
       "code": "FIN",
       "created_at": "2026-11-03T08:14:02Z",
       "next_check_at": "2026-11-20"},
      {"priority": 2, "text": "Re-rate after earnings"}
    ]}'
```

## Related read endpoints (open)

- `GET /api/v1/companies` — directory with bands and watch items inline
  (`query`, `layer` (repeatable), `segment`, `funnel_tier`, `ingestion_status`,
  `sort_by`, `order`, `limit` ≤ 100, `offset`).
- `GET /api/v1/quotes` — cached prices + `generated_at`.
- `GET /api/v1/funnel/tiers` — resolved per-ticker tier index.
