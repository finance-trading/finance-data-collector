# Strategy Company Universe + QDCR Homepage Design

## Status

Design approved in conversation on 2026-09-28. This document defines the homepage information architecture only; it does not authorize frontend implementation yet.

## Goal

Make the existing homepage a strategy company list that answers two related questions without conflating them:

1. Where is each company in the four-layer screening funnel?
2. For a company-specific event, what is the current QDCR assessment and its evidence state?

The homepage remains a company list. QDCR is a company/event assessment shown in each row and expanded inline; it is not a separate top-level page.

## Source boundaries

The design follows these repository documents:

- `docs/strategy/0910 策略.md` for the QDCR assessment dimensions and research context.
- `docs/strategy/chat.md` for the strategy intent, prediction-versus-trading distinction, and mechanical baseline.
- `docs/strategy/quality-company-temporary-dislocation-strategy-v0.md` for the strategy funnel and investment discipline.
- `docs/strategy/four-layer-screening-rules-v0.md` for the canonical four-layer statuses and fail-closed boundaries.
- `docs/strategy/core-quality-watchlist-v0.md` for the provisional watchlist and evidence caveats.

The strategy universe starts from the current S&P 500 snapshot (500 companies after CIK consolidation in the source document), then narrows through the four layers. The current AI company catalog remains available as a separate auxiliary view and filter; it is not the strategy universe.

## Information architecture

The homepage layout is **B: layered list with inline expansion**.

### Persistent shell

Keep the current product shell and navigation. The Companies route is the strategy homepage. Existing Company, Company Graph, AI Layers, and Evidence routes remain available and are not replaced by this design.

### Homepage sections, in order

1. **Page header**
   - Title: `Strategy company universe`.
   - Subtitle: explain that the list moves from screening to event research.
   - As-of date, strategy version, and research-only/provisional badge.

2. **Screening pipeline**
   - Five compact stages:
     - Layer 1 — Universe Eligibility
     - Layer 2 — Mechanical Quality
     - Layer 3 — Core Watchlist Fit
     - Layer 4 — Event & Investment Gate
     - Decision — research outcome
   - Each stage shows the count and a short status summary.
   - Selecting a stage filters the table to that stage; it does not mutate company conclusions.

3. **Filter bar**
   - Search by ticker or company name.
   - Layer 1 status.
   - Layer 2 quality status.
   - Layer 3 watchlist status.
   - Layer 4 event status.
   - AI layer / segment as an auxiliary filter.
   - Filters are URL-addressable so a filtered state can be bookmarked and shared.

4. **Company list**
   - One row per company.
   - Fixed summary columns: Company, Screening stage, Quality, Dislocation, Catalyst, Risk / Position, Decision.
   - The four QDCR columns are always present for comparison.
   - A row disclosure control expands the company in place.

5. **Expanded company detail**
   - Left: screening history from Layer 1 through Layer 4.
   - Right: four QDCR module cards, each with a status, child fields, evidence freshness, and an optional evidence link.
   - Child fields can open a compact evidence/detail affordance without navigating away from the company list.

## Four-layer semantics

The UI must preserve the one-way funnel. A later layer cannot rewrite an earlier layer.

| Layer | UI label | Question | Allowed outputs |
|---|---|---|---|
| 1 | Universe Eligibility | Can the company be compared with the ordinary-company model? | `ELIGIBLE_ORDINARY`, `SEPARATE_MODEL`, `UNAVAILABLE`, `OUT_OF_UNIVERSE` |
| 2 | Mechanical Quality | Did pre-event five-year data meet the mechanical quality gates? | `PASS_COMPLETE`, `PASS_REVIEW_REQUIRED`, `FAIL`, `DATA_CONFLICT`, `UNAVAILABLE` |
| 3 | Core Watchlist Fit | Can the team understand, monitor, and falsify the company over time? | `CORE_WATCHLIST`, `RESERVE`, `BROAD_RESEARCH_ONLY`, `REMOVE_FROM_CORE` |
| 4 | Event & Investment Gate | Is this specific event a temporary problem with mispricing? | `PROVISIONAL_BUY_CANDIDATE`, `WATCH`, `AVOID`, `BLOCKED`, `NO_ACTION` |

Rules:

- `PASS` never means `BUY`.
- The existing 23-company list remains visibly `PROVISIONAL` until all 96 Layer 2 passers receive the uniform Layer 3 dual review.
- Missing critical evidence fails closed before Layer 4; it cannot be rendered as a positive conclusion.
- The UI must retain `UNAVAILABLE`, `DATA_CONFLICT`, and `BLOCKED` rather than filling gaps with inferred values.

## QDCR semantics

QDCR is displayed as four independent modules. A combined “score” is intentionally not introduced; the four states must remain separately interpretable.

### Quality

Quality is based on evidence available before the event. It is not a post-drop belief that the company will recover.

Child fields may include:

- moat / competitive advantage;
- market space and customer need;
- cash-flow quality and margins;
- switching costs, retention, or measurable stickiness;
- balance sheet and survival risk;
- capital allocation and reinvestment.

### Dislocation

Dislocation describes the event and the gap between price movement and economic-value change.

Child fields may include:

- 1-day, 5-day, and 20-day returns;
- relative return versus sector or relevant risk theme;
- estimate revisions;
- multiple compression;
- event impact on revenue, margins, and FCF;
- price loss versus fair-value loss.

If no company-specific event has been registered, the cell reads `Not triggered`, not `None` and not a fabricated low score.

### Catalyst

Catalyst describes observable checkpoints that could change the market’s view.

Child fields may include:

- earnings or guidance date;
- product launch or customer checkpoint;
- analyst estimate revision trend;
- operational KPI checkpoint;
- expected validation window.

This module can be `Not triggered` until Layer 4 research begins.

### Risk / Position

Risk / Position combines event risk and portfolio constraints only when the required evidence exists.

Child fields may include:

- macro and market breadth;
- single-name risk;
- portfolio correlation;
- sector and shared-theme concentration;
- current position and suggested size.

When the portfolio ledger or correlation inputs are missing, display `Unavailable` or `Blocked`; never imply that a position size is safe.

## State presentation

Text is the primary semantic channel. Color and dots are secondary affordances.

- Positive / complete: teal.
- Review / provisional: amber.
- Risk / fail: red.
- Not triggered / unavailable: muted slate.
- Informational checkpoint: blue.

Status labels must be explicit. Do not use color alone, and do not reuse one color for `Moderate`, `Not Clear`, and `High`.

Recommended labels for the compact table are short, while expanded detail uses the canonical machine status and explanatory text. Every status has an accessible label and a tooltip or inline explanation where the short label could be ambiguous.

## Interaction model

- Clicking the disclosure control expands one company row inline.
- Expanding a second row collapses the first to keep the list scannable.
- Clicking a pipeline stage applies the corresponding filter and keeps the selected stage visually active.
- Changing any filter updates the URL without a full page reload.
- Clicking a child field opens its evidence/detail affordance in the expanded row or navigates to the existing Evidence route with company and field context.
- Keyboard users can reach filters, disclosure controls, stage controls, and evidence links in a predictable order.
- Touch targets are at least 44px high where controls are interactive.

## Data contract direction

The implementation should adapt the existing company directory response rather than duplicate company identity logic. The homepage view model should eventually provide:

```ts
interface StrategyCompanyRow {
  ticker: string;
  company_name: string;
  sector: string | null;
  ai_layer: string | null;
  screening: {
    layer1: LayerStatus;
    layer2: LayerStatus;
    layer3: LayerStatus;
    layer4: LayerStatus;
    decision: string;
  };
  qdcr: {
    quality: QdcrModule;
    dislocation: QdcrModule;
    catalyst: QdcrModule;
    risk_position: QdcrModule;
  };
}

interface QdcrModule {
  status: string;
  state: "complete" | "review" | "not_triggered" | "unavailable" | "blocked";
  fields: Array<{label: string; value: string; evidence?: string; as_of?: string}>;
}
```

This is a UI-facing direction, not permission to invent API data. Until a backend source exists, the frontend must render missing modules using explicit unavailable states and keep demo fixtures isolated from live data.

## Loading and error behavior

- The pipeline and table have independent loading states so a slow QDCR payload does not blank the company identity list.
- If company identity loads but screening/QDCR data fails, preserve the company row and show `Unavailable` / `Blocked` in affected modules.
- If the strategy universe endpoint fails, use the existing directory error pattern with retry and a clear source label; do not silently fall back to the AI catalog as if it were the strategy universe.
- Empty filtered results explain which filters are active and offer a clear-filter action.
- Pagination remains explicit; the initial design does not require loading all 500 companies into the browser at once.

## Accessibility and responsive behavior

- Use semantic table/list structure with header associations for QDCR columns.
- Disclosure controls expose `aria-expanded` and a relationship to the expanded detail region.
- Status text remains visible to screen readers; decorative dots use `aria-hidden`.
- Preserve visible focus rings and keyboard navigation.
- Desktop is the primary dense research layout. At narrower widths, the table may scroll horizontally, but the Company and disclosure columns remain sticky; expanded QDCR modules stack in a readable order.

## Verification plan for implementation

Before implementation is considered complete, verify:

1. The homepage still renders the existing directory when strategy fields are unavailable.
2. All four QDCR columns remain visible and distinguish `Not triggered`, `Unavailable`, and `Blocked`.
3. Each four-layer status maps to the canonical status vocabulary and does not imply buy authorization.
4. A provisional Layer 3 company cannot appear as a formal core company merely because it is in the existing 23-name list.
5. Filters compose correctly, persist in the URL, and never replace the full strategy universe with the AI catalog.
6. Row expansion and evidence links work with keyboard input and have accessible names.
7. Loading, partial failure, empty results, and retry states are visible and truthful.
8. Existing Company, AI Layers, Graph, and Evidence routes remain unaffected.

## Out of scope

- Creating a new QDCR page.
- Changing strategy thresholds or upgrading v0 to a live trading authorization rule.
- Treating the current 23-company provisional watchlist as a formally approved core pool.
- Building a portfolio ledger or inventing correlation/position data.
- Replacing the existing AI Layers page.
