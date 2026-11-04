import { apiGet, apiPost } from "../api/client";
import type {
  CatalogLayerListView,
  CompanyDirectoryItem,
  CompanyDirectoryView,
  FunnelTierInfo,
  IngestionStatus,
  PriceRange,
  QuotesPayload,
  WatchItem,
} from "../api/types";
import { renderDataState } from "../components/data-state";
import { renderPagination } from "../components/pagination";

export type DirectorySortKey =
  | "market_cap"
  | "change_pct"
  | "week_change_pct"
  | "week_rise_pct"
  | "change_52w_pct"
  | "rise_52w_pct";

export type DirectorySort = `${DirectorySortKey}_${"desc" | "asc"}`;

export interface DirectoryState {
  query: string;
  layers: string[];
  segment: string;
  tier: "" | "1" | "2" | "3";
  status: "" | IngestionStatus;
  sort: "" | DirectorySort;
  page: number;
  pageSize: 25 | 50 | 100;
}

const tiers = new Set<DirectoryState["tier"]>(["", "1", "2", "3"]);

const statuses = new Set<IngestionStatus>([
  "parsed",
  "failed",
  "unavailable",
  "not_ingested",
]);
const pageSizes = new Set([25, 50, 100]);
const sorts = new Set<DirectorySort>([
  "market_cap_desc",
  "market_cap_asc",
  "change_pct_desc",
  "change_pct_asc",
  "week_change_pct_desc",
  "week_change_pct_asc",
  "week_rise_pct_desc",
  "week_rise_pct_asc",
  "change_52w_pct_desc",
  "change_52w_pct_asc",
  "rise_52w_pct_desc",
  "rise_52w_pct_asc",
]);

export function readDirectoryState(search: URLSearchParams): DirectoryState {
  const rawStatus = search.get("status") ?? "";
  const rawSort = search.get("sort") ?? "";
  const rawPage = Number(search.get("page") ?? "1");
  const rawPageSize = Number(search.get("pageSize") ?? "25");
  const rawTier = search.get("tier") ?? "";
  return {
    query: search.get("query")?.trim() ?? "",
    layers: [...new Set(search.getAll("layer").filter(Boolean))],
    segment: search.get("segment") ?? "",
    tier: tiers.has(rawTier as DirectoryState["tier"])
      ? (rawTier as DirectoryState["tier"])
      : "",
    status: statuses.has(rawStatus as IngestionStatus)
      ? (rawStatus as IngestionStatus)
      : "",
    sort: sorts.has(rawSort as DirectorySort) ? (rawSort as DirectorySort) : "",
    page: Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: pageSizes.has(rawPageSize)
      ? (rawPageSize as DirectoryState["pageSize"])
      : 25,
  };
}

export function writeDirectoryState(state: DirectoryState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.query) params.set("query", state.query);
  state.layers.forEach((layer) => params.append("layer", layer));
  if (state.segment) params.set("segment", state.segment);
  if (state.tier) params.set("tier", state.tier);
  if (state.status) params.set("status", state.status);
  if (state.sort) params.set("sort", state.sort);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}

function formatDate(value: string | null): string {
  if (!value) return "No filing date";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

/** Last-refresh stamp for the quote cache; the refresh job runs post-close, so UTC reads naturally. */
export function formatRefreshTime(value: string | null): string {
  if (!value) return "";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

/** Market cap in millions of USD ("$5,574,102M"). */
function formatMarketCapMillions(value: number): string {
  const millions = value / 1e6;
  return millions >= 1000
    ? `$${Math.round(millions).toLocaleString("en-US")}M`
    : `$${millions.toFixed(1)}M`;
}

/** Two decimals with separators: P/E and EPS columns. */
function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

/** Public quote page for a ticker, e.g. `ASML` -> https://stockanalysis.com/stocks/asml/ */
export function stockAnalysisUrl(ticker: string): string {
  const slug = ticker.trim().toLowerCase().replace(/[.\s]+/g, "-");
  return `https://stockanalysis.com/stocks/${encodeURIComponent(slug)}/`;
}

function cell(label: string, className = ""): HTMLTableCellElement {
  const element = document.createElement("td");
  element.dataset.label = label;
  element.className = className;
  return element;
}

/** The sort key a `*_asc`/`*_desc` state value refers to, or null for catalog order. */
export function sortKeyOf(sort: DirectoryState["sort"]): DirectorySortKey | null {
  if (!sort) return null;
  return sort.slice(0, sort.lastIndexOf("_")) as DirectorySortKey;
}

/**
 * Next sort value after activating `key` from `sort`.
 *
 * A fresh column starts descending — biggest cap, biggest gainer first, matching
 * the server default. Activating the column that is already sorted flips it.
 */
export function nextSort(
  sort: DirectoryState["sort"],
  key: DirectorySortKey,
): DirectorySort {
  const direction =
    sortKeyOf(sort) === key && sort?.endsWith("_desc") ? "asc" : "desc";
  return `${key}_${direction}` as DirectorySort;
}

/** Reflect the active sort onto the header cells: `aria-sort` plus a direction arrow. */
export function syncSortHeaders(sort: DirectoryState["sort"]): void {
  const active = sortKeyOf(sort);
  document.querySelectorAll<HTMLTableCellElement>("th[data-sort-column]").forEach((header) => {
    const order =
      header.dataset.sortColumn !== active
        ? "none"
        : sort?.endsWith("_asc")
          ? "ascending"
          : "descending";
    header.setAttribute("aria-sort", order);
    const indicator = header.querySelector(".sort-indicator");
    if (indicator) {
      indicator.textContent = order === "ascending" ? "▲" : order === "descending" ? "▼" : "";
    }
  });
}

export function renderCompanies(
  companies: CompanyDirectoryItem[],
  target: HTMLTableSectionElement | null = document.querySelector(
    "#company-directory-body",
  ),
  onTierSaved?: () => void,
): void {
  if (!target) return;
  target.replaceChildren();

  companies.forEach((company) => {
    const row = document.createElement("tr");
    const companyCell = cell("Company", "company-cell");
    const identity = document.createElement("a");
    identity.className = "company-identity";
    identity.href = stockAnalysisUrl(company.ticker);
    identity.target = "_blank";
    identity.rel = "noopener noreferrer";
    const ticker = document.createElement("strong");
    ticker.textContent = company.ticker;
    const name = document.createElement("span");
    name.textContent = company.name;
    name.title = company.name;
    identity.append(ticker, name);
    companyCell.append(identity);

    const categoryCell = cell("AI layer", "category-cell");
    const layer = document.createElement("strong");
    layer.textContent = company.layer_name;
    const segment = document.createElement("span");
    segment.textContent = company.segment;
    categoryCell.append(layer, segment);

    const tierCell = makeTierCell(company, onTierSaved);

    const dateCell = cell("Latest filing", "date-cell");
    dateCell.textContent = formatDate(company.latest_filing_date);

    const priceCell = cell("Price", "number-column price-cell");
    if (company.price !== null && company.price !== undefined) {
      const price = document.createElement("span");
      price.className = "price-value";
      price.textContent = new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(company.price);
      priceCell.append(price);
      if (company.change_pct !== null && company.change_pct !== undefined) {
        priceCell.append(changeBadge(company.change_pct));
      }
    } else {
      const na = document.createElement("span");
      na.className = "price-na";
      na.textContent = "—";
      priceCell.append(na);
    }

    const capCell = cell("Market cap", "number-column cap-cell");
    if (company.market_cap !== null && company.market_cap !== undefined) {
      const cap = document.createElement("span");
      cap.className = "cap-value";
      cap.textContent = formatMarketCapMillions(company.market_cap);
      capCell.append(cap);
    } else {
      const na = document.createElement("span");
      na.className = "cap-na";
      na.textContent = "—";
      capCell.append(na);
    }

    const actionCell = cell("Action", "action-cell");
    if (company.research_available) {
      const action = document.createElement("a");
      action.href = `company.html?ticker=${encodeURIComponent(company.ticker)}`;
      action.setAttribute("aria-label", `Open ${company.ticker} filing workspace`);
      action.textContent = "Open";
      actionCell.append(action);
    } else {
      const unavailable = document.createElement("span");
      unavailable.className = "availability availability-missing";
      unavailable.textContent = "—";
      actionCell.append(unavailable);
    }

    row.append(
      companyCell,
      categoryCell,
      tierCell,
      dateCell,
      priceCell,
      changeCell("1W DD", company.week_change_pct),
      changeCell("1W Rise", company.week_rise_pct),
      changeCell("52W DD", company.change_52w_pct),
      changeCell("52W Rise", company.rise_52w_pct),
      ratioCell("P/E", company.pe),
      ratioCell("EPS", company.eps_ttm),
      ratioCell("Fwd P/E", company.forward_pe),
      ratioCell("Fwd EPS", company.forward_eps),
      capCell,
      observationBandCell(company),
      watchItemsCell(company),
      actionCell,
    );
    target.append(row);
  });
}

/** A signed percentage badge: green up, red down, neutral flat. */
function changeBadge(pct: number): HTMLSpanElement {
  const badge = document.createElement("span");
  badge.className = `price-change ${pct > 0 ? "up" : pct < 0 ? "down" : "flat"}`;
  badge.textContent =
    pct > 0
      ? `▲ ${pct.toFixed(2)}%`
      : pct < 0
        ? `▼ ${Math.abs(pct).toFixed(2)}%`
        : "— 0.00%";
  return badge;
}

function changeCell(label: string, pct: number | null | undefined): HTMLTableCellElement {
  const element = cell(label, "number-column change-cell");
  if (pct !== null && pct !== undefined) {
    element.append(changeBadge(pct));
  } else {
    const na = document.createElement("span");
    na.className = "price-na";
    na.textContent = "—";
    element.append(na);
  }
  return element;
}

function ratioCell(label: string, value: number | null | undefined): HTMLTableCellElement {
  const element = cell(label, "number-column ratio-cell");
  const span = document.createElement("span");
  span.textContent = formatRatio(value);
  element.append(span);
  return element;
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"}).format(value);
}

/** Four user-entered price intervals. No price is inferred from tier triggers. */
const rangeFields = [
  ["observation_range", "观察"],
  ["entry_range", "建仓"],
  ["add_range", "补仓"],
  ["reduce_range", "减仓"],
] as const;

type RangeField = typeof rangeFields[number][0];

async function saveAnnotation(company: CompanyDirectoryItem, changes: Record<string, unknown>): Promise<void> {
  await apiPost(
    `/api/v1/research/annotations/${encodeURIComponent(company.ticker)}`,
    {body: changes},
  );
  company.annotation_saved = true;
}

export function observationBandCell(company: CompanyDirectoryItem): HTMLTableCellElement {
  const element = cell("Price ranges", "obs-cell");
  const render = (): void => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "annotation-edit";
    button.textContent = "编辑区间";
    button.setAttribute("aria-label", `${company.ticker} 编辑价格区间`);
    button.addEventListener("click", edit);
    const ranges = document.createElement("div");
    ranges.className = "range-list";
    for (const [field, label] of rangeFields) {
      const band = company[field];
      const line = document.createElement("div");
      line.textContent = `${label}：${band?.low != null && band?.high != null ? `${formatUsd(band.low)}–${formatUsd(band.high)}` : "—"}`;
      ranges.append(line);
    }
    element.replaceChildren(ranges, button);
  };
  const edit = (): void => {
    const form = document.createElement("form");
    form.className = "annotation-editor";
    const inputs = {} as Record<RangeField, [HTMLInputElement, HTMLInputElement]>;
    for (const [field, label] of rangeFields) {
      const line = document.createElement("div");
      line.className = "range-edit-row";
      const title = document.createElement("span");
      title.textContent = label;
      const band = company[field];
      const pair = (["low", "high"] as const).map((end) => {
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0.01";
        input.step = "0.01";
        input.placeholder = end === "low" ? "低" : "高";
        input.setAttribute("aria-label", `${company.ticker} ${label}${end === "low" ? "低" : "高"}价`);
        input.value = band?.[end] == null ? "" : String(band[end]);
        return input;
      }) as [HTMLInputElement, HTMLInputElement];
      inputs[field] = pair;
      line.append(title, pair[0], pair[1]);
      form.append(line);
    }
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "保存";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", render);
    const error = document.createElement("span");
    error.className = "annotation-error";
    error.setAttribute("role", "alert");
    form.append(save, cancel, error);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const ranges = {} as Record<RangeField, PriceRange>;
      for (const [field] of rangeFields) {
        const [low, high] = inputs[field];
        if (Boolean(low.value) !== Boolean(high.value) || (low.value && (+low.value > +high.value || +low.value <= 0))) {
          error.textContent = "请填写完整且有效的区间（低价 ≤ 高价）";
          return;
        }
        ranges[field] = {low: low.value ? +low.value : null, high: high.value ? +high.value : null};
      }
      const controls = form.querySelectorAll<HTMLInputElement | HTMLButtonElement>("input, button");
      controls.forEach((control) => { control.disabled = true; });
      try {
        await saveAnnotation(company, ranges);
        Object.assign(company, ranges);
        render();
      } catch (cause) {
        console.error(cause);
        error.textContent = "保存失败，请重试";
        controls.forEach((control) => { control.disabled = false; });
      }
    });
    element.replaceChildren(form);
    inputs.observation_range[0].focus();
  };
  render();
  return element;
}

/** Editable company watch items, P1 high → P3 low; labels supplement color. */
export function watchItemsCell(company: CompanyDirectoryItem): HTMLTableCellElement {
  const element = cell("Watch items", "watch-cell");
  const render = (): void => {
    const list = document.createElement("ul");
    list.className = "watch-list";
    for (const item of [...(company.watch_items ?? [])].sort((a, b) => a.priority - b.priority)) {
      const row = document.createElement("li");
      row.className = `watch-item p${item.priority}`;
      row.title = [item.text, item.next_check_at ? `下次关注 ${item.next_check_at.slice(0, 10)}` : ""]
        .filter(Boolean)
        .join(" · ");
      const priority = document.createElement("span");
      priority.className = "watch-priority";
      priority.textContent = `P${item.priority}`;
      row.append(priority);
      if (item.code) {
        const code = document.createElement("span");
        code.className = "watch-code";
        code.textContent = item.code;
        row.append(code);
      }
      const text = document.createElement("span");
      text.className = "watch-text";
      text.textContent = item.text;
      row.append(text);
      list.append(row);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "annotation-edit";
    button.textContent = "编辑事项";
    button.setAttribute("aria-label", `${company.ticker} 编辑观察事项`);
    button.addEventListener("click", edit);
    element.replaceChildren(list, button);
  };
  const edit = (): void => {
    const form = document.createElement("form");
    form.className = "annotation-editor watch-editor";
    const rows = document.createElement("div");
    const appendRow = (item: WatchItem = {priority: 2, text: ""}): void => {
      if (rows.children.length >= 50) return;
      const line = document.createElement("div");
      line.className = "watch-edit-row";
      const select = document.createElement("select");
      select.setAttribute("aria-label", `${company.ticker} 事项优先级`);
      ([1, 2, 3] as const).forEach((priority) => select.append(option(String(priority), `P${priority}`)));
      select.value = String(item.priority);
      const codeInput = document.createElement("input");
      codeInput.type = "text";
      codeInput.maxLength = 32;
      codeInput.value = item.code ?? "";
      codeInput.placeholder = "code";
      codeInput.className = "watch-code-input";
      codeInput.setAttribute("aria-label", `${company.ticker} 事项分类 code`);
      const input = document.createElement("input");
      input.type = "text";
      input.maxLength = 500;
      input.value = item.text;
      input.placeholder = "观察事项";
      input.className = "watch-text-input";
      input.setAttribute("aria-label", `${company.ticker} 观察事项`);
      const nextCheck = document.createElement("input");
      nextCheck.type = "date";
      nextCheck.value = item.next_check_at?.slice(0, 10) ?? "";
      nextCheck.className = "watch-next-check-input";
      nextCheck.setAttribute("aria-label", `${company.ticker} 下次关注时间`);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "删除";
      remove.setAttribute("aria-label", `${company.ticker} 删除观察事项`);
      remove.addEventListener("click", () => line.remove());
      if (item.created_at) line.dataset.createdAt = item.created_at;
      line.append(select, codeInput, input, nextCheck, remove);
      rows.append(line);
    };
    (company.watch_items ?? []).forEach(appendRow);
    const add = document.createElement("button");
    add.type = "button";
    add.textContent = "+ 添加事项";
    add.addEventListener("click", () => appendRow());
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "保存";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", render);
    const error = document.createElement("span");
    error.className = "annotation-error";
    error.setAttribute("role", "alert");
    form.append(rows, add, save, cancel, error);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const items = [...rows.querySelectorAll<HTMLElement>(".watch-edit-row")].map((row): WatchItem => {
        const item: WatchItem = {
          priority: Number(row.querySelector<HTMLSelectElement>("select")!.value) as WatchItem["priority"],
          text: row.querySelector<HTMLInputElement>(".watch-text-input")!.value.trim(),
        };
        const code = row.querySelector<HTMLInputElement>(".watch-code-input")!.value.trim();
        if (code) item.code = code;
        const nextCheck = row.querySelector<HTMLInputElement>(".watch-next-check-input")!.value;
        if (nextCheck) item.next_check_at = nextCheck;
        // Keep the server-stamped creation time when the row was an existing item.
        if (row.dataset.createdAt) item.created_at = row.dataset.createdAt;
        return item;
      });
      if (items.some((item) => !item.text)) {
        error.textContent = "观察事项不能为空";
        return;
      }
      const controls = form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>("input, select, button");
      controls.forEach((control) => { control.disabled = true; });
      try {
        await saveAnnotation(company, {watch_items: items});
        company.watch_items = items;
        render();
      } catch (cause) {
        console.error(cause);
        error.textContent = "保存失败，请重试";
        controls.forEach((control) => { control.disabled = false; });
      }
    });
    element.replaceChildren(form);
  };
  render();
  return element;
}

/**
 * The Tier column cell: a badge that toggles into an inline editor. Picking a
 * tier (or 自动) persists to `config/funnel_overrides.json` via the API and
 * re-renders the badge from the returned resolved tier, so the change shows up
 * live without a page reload.
 */
function makeTierCell(company: CompanyDirectoryItem, onSaved?: () => void): HTMLTableCellElement {
  const td = cell("Funnel tier", "tier-cell");
  td.dataset.ticker = company.ticker;

  const tierBadge = (): HTMLButtonElement => {
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = `tier-badge tier-${company.funnel_tier ?? "na"} tier-editable`;
    if (company.funnel_tier_source) badge.dataset.source = company.funnel_tier_source;
    badge.title =
      [
        company.funnel_tier === null || company.funnel_tier === undefined
          ? ""
          : `T${company.funnel_tier} ${company.funnel_tier_name ?? ""}`.trim(),
        company.funnel_tier_source ? `Source: ${company.funnel_tier_source}` : "",
        company.funnel_tier_note ? company.funnel_tier_note : "",
        "Click to edit tier",
      ]
        .filter(Boolean)
        .join("\n");
    badge.textContent =
      company.funnel_tier === null || company.funnel_tier === undefined
        ? "—"
        : company.funnel_tier_name
          ? `T${company.funnel_tier} ${company.funnel_tier_name}`
          : `T${company.funnel_tier}`;
    badge.addEventListener("click", () => toggleEditor());
    return badge;
  };

  const toggleEditor = (): void => {
    const form = document.createElement("form");
    form.className = "tier-editor";
    const select = document.createElement("select");
    select.setAttribute("aria-label", `${company.ticker} tier`);
    (["1", "2", "3", "auto"] as const).forEach((value) => {
      select.append(option(value, value === "auto" ? "自动分档" : `T${value} ${tierName(value)}`));
    });
    select.value = company.funnel_tier_source === "人工" ? String(company.funnel_tier) : "auto";
    const note = document.createElement("input");
    note.type = "text";
    note.placeholder = "调整原因";
    note.setAttribute("aria-label", `${company.ticker} 调整原因`);
    note.value = company.funnel_tier_note ?? "";
    note.hidden = select.value === "auto";
    note.required = !note.hidden;
    select.addEventListener("change", () => {
      note.hidden = select.value === "auto";
      note.required = !note.hidden;
    });
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "保存";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "取消";
    cancel.addEventListener("click", () => td.replaceChildren(tierBadge()));
    const error = document.createElement("span");
    error.className = "tier-error";
    error.setAttribute("role", "alert");
    form.append(select, note, save, cancel, error);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const tier = select.value === "auto" ? null : Number(select.value);
      if (tier !== null && !note.value.trim()) {
        error.textContent = "请填写调整原因";
        note.focus();
        return;
      }
      save.disabled = true;
      cancel.disabled = true;
      select.disabled = true;
      note.disabled = true;
      error.textContent = "保存中…";
      try {
        const resolved = await apiPost<FunnelTierInfo>("/api/v1/funnel/overrides", {
          body: {ticker: company.ticker, tier, note: tier === null ? null : note.value.trim()},
        });
        company.funnel_tier = resolved.tier;
        company.funnel_tier_name = resolved.tier_name;
        company.funnel_tier_source = resolved.source;
        company.funnel_tier_note = resolved.note || null;
        if (onSaved) onSaved();
        else td.replaceChildren(tierBadge());
      } catch (cause) {
        console.error(cause);
        error.textContent = "保存失败，请重试";
        save.disabled = false;
        cancel.disabled = false;
        select.disabled = false;
        note.disabled = false;
      }
    });
    td.replaceChildren(form);
    select.focus();
  };

  td.append(tierBadge());
  return td;
}

const TIER_NAMES: Record<string, string> = {
  "1": "核心",
  "2": "重要",
  "3": "观察",
};

function tierName(value: string): string {
  return TIER_NAMES[value] ?? "";
}

function option(value: string, label: string): HTMLOptionElement {
  const element = document.createElement("option");
  element.value = value;
  element.textContent = label;
  return element;
}

export async function mountDirectory(): Promise<void> {
  const app = document.querySelector<HTMLElement>("[data-directory-app]");
  if (!app) return;

  const form = document.querySelector<HTMLFormElement>("#company-search-form")!;
  const query = document.querySelector<HTMLInputElement>("#company-search")!;
  const layer = document.querySelector<HTMLDetailsElement>("#layer-filter")!;
  const layerOptions = layer.querySelector<HTMLElement>(".layer-filter-options")!;
  const layerSummary = document.querySelector<HTMLElement>("#layer-filter-summary")!;
  const segment = document.querySelector<HTMLSelectElement>("#segment-filter")!;
  const tier = document.querySelector<HTMLSelectElement>("#tier-filter")!;
  const status = document.querySelector<HTMLSelectElement>("#status-filter")!;
  
  const pageSize = document.querySelector<HTMLSelectElement>("#page-size")!;
  const directoryState = document.querySelector<HTMLElement>("#directory-state")!;
  const pagination = document.querySelector<HTMLElement>("#directory-pagination")!;
  const companyTotal = document.querySelector<HTMLElement>("#company-total")!;
  const filingTotal = document.querySelector<HTMLElement>("#filing-total")!;
  const quoteAsOf = document.querySelector<HTMLElement>("#quote-as-of")!;
  const quoteRefresh = document.querySelector<HTMLButtonElement>("#quote-refresh")!;
  let state = readDirectoryState(new URL(window.location.href).searchParams);
  let controller: AbortController | null = null;
  let layers: CatalogLayerListView | null = null;
  let quoteAsOfDate: string | null | undefined;
  let refreshedAt: string | null = null;

  const renderQuoteNote = (): void => {
    const parts: string[] = [];
    if (quoteAsOfDate) {
      parts.push(
        `Price, 1W/52W drawdown and rise, and market cap as of ${formatDate(quoteAsOfDate)} close.`,
      );
    }
    if (refreshedAt) {
      parts.push(`Last refreshed ${formatRefreshTime(refreshedAt)}.`);
    }
    quoteAsOf.hidden = parts.length === 0;
    quoteAsOf.textContent = parts.join(" ");
  };

  const updateSegments = (): void => {
    const selected = state.segment;
    const currentLayer = state.layers.length === 1
      ? layers?.layers.find((item) => item.id === state.layers[0])
      : null;
    segment.replaceChildren(option("", "All segments"));
    const names = currentLayer
      ? currentLayer.segments.map((item) => item.name)
      : [...new Set(layers?.layers.flatMap((item) => item.segments.map((part) => part.name)) ?? [])];
    names.forEach((name) => segment.append(option(name, name)));
    segment.value = names.includes(selected) ? selected : "";
    if (!segment.value) state.segment = "";
  };

  const syncControls = (): void => {
    query.value = state.query;
    layerOptions.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.checked = state.layers.includes(checkbox.value);
    });
    layerSummary.textContent = state.layers.length ? `${state.layers.length} layers selected` : "All layers";
    tier.value = state.tier;
    status.value = state.status;
    pageSize.value = String(state.pageSize);
    updateSegments();
    syncSortHeaders(state.sort);
  };

  const load = async (): Promise<void> => {
    controller?.abort();
    controller = new AbortController();
    const request = controller;
    renderDataState(directoryState, "loading", "Reading the AI company catalog…");
    const params = new URLSearchParams();
    if (state.query) params.set("query", state.query);
    state.layers.forEach((layer) => params.append("layer", layer));
    if (state.segment) params.set("segment", state.segment);
    if (state.tier) params.set("funnel_tier", state.tier);
    if (state.status) params.set("ingestion_status", state.status);
    if (state.sort) {
      const separator = state.sort.endsWith("_desc") ? "_desc" : "_asc";
      params.set("sort_by", state.sort.slice(0, -separator.length));
      params.set("order", separator === "_desc" ? "desc" : "asc");
    }
    params.set("limit", String(state.pageSize));
    params.set("offset", String((state.page - 1) * state.pageSize));

    try {
      const payload = await apiGet<CompanyDirectoryView>(
        "/api/v1/companies",
        params,
        request.signal,
      );
      if (request !== controller) return;
      if (payload.total && payload.companies.length === 0 && state.page > 1) {
        state.page = Math.ceil(payload.total / state.pageSize);
        await load();
        return;
      }
      renderCompanies(payload.companies, undefined, () => void load());
      companyTotal.textContent = new Intl.NumberFormat("en").format(payload.total);
      filingTotal.textContent = new Intl.NumberFormat("en").format(
        payload.companies.reduce((total, company) => total + company.filing_count, 0),
      );
      quoteAsOfDate = payload.companies.find((company) => company.quote_as_of)
        ?.quote_as_of;
      renderQuoteNote();
      renderPagination(
        pagination,
        {page: state.page, pageSize: state.pageSize, total: payload.total},
        (page) => {
          state.page = page;
          history.replaceState(null, "", `?${writeDirectoryState(state)}`);
          void load();
        },
      );
      renderDataState(
        directoryState,
        payload.total ? "ready" : "empty",
        payload.total
          ? ""
          : "No companies match these filters. Clear a filter and try again.",
      );
      history.replaceState(null, "", `?${writeDirectoryState(state)}`);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      renderCompanies([]);
      renderDataState(
        directoryState,
        "error",
        "The company directory could not be loaded. Check the service and try again.",
        () => void load(),
      );
      console.error(error);
    }
  };

  try {
    layers = await apiGet<CatalogLayerListView>("/api/v1/catalog/layers");
    layers.layers.forEach((item) => {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = item.id;
      label.append(checkbox, `${item.name} (${item.count})`);
      layerOptions.append(label);
    });
    syncControls();
  } catch (error) {
    console.error(error);
  }
  apiGet<QuotesPayload>("/api/v1/quotes")
    .then((payload) => {
      refreshedAt = payload.generated_at;
      renderQuoteNote();
    })
    .catch((error) => console.error(error));
  quoteRefresh.addEventListener("click", () => {
    quoteRefresh.disabled = true;
    quoteRefresh.textContent = "Refreshing…";
    apiPost<QuotesPayload>("/api/v1/quotes/refresh")
      .then((payload) => {
        refreshedAt = payload.generated_at;
        renderQuoteNote();
        return load();
      })
      .catch((error) => {
        console.error(error);
        quoteAsOf.hidden = false;
        quoteAsOf.textContent = "Price refresh failed — try again.";
      })
      .finally(() => {
        quoteRefresh.disabled = false;
        quoteRefresh.textContent = "Refresh prices";
      });
  });
  syncControls();

  const applyFilters = (): void => {
    state = {
      ...state,
      query: query.value.trim(),
      layers: [...layerOptions.querySelectorAll<HTMLInputElement>('input:checked')].map((input) => input.value),
      segment: segment.value,
      tier: tier.value as DirectoryState["tier"],
      status: status.value as DirectoryState["status"],
      page: 1,
      pageSize: Number(pageSize.value) as DirectoryState["pageSize"],
    };
    updateSegments();
    syncControls();
    history.replaceState(null, "", `?${writeDirectoryState(state)}`);
    void load();
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    applyFilters();
  });
  query.addEventListener("search", () => applyFilters());
  layer.addEventListener("change", () => {
    state.segment = "";
    applyFilters();
  });
  segment.addEventListener("change", () => applyFilters());
  tier.addEventListener("change", () => applyFilters());
  status.addEventListener("change", () => applyFilters());
  document.querySelectorAll<HTMLButtonElement>(".sort-button").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort as DirectorySortKey;
      state = { ...state, sort: nextSort(state.sort, key), page: 1 };
      syncSortHeaders(state.sort);
      history.replaceState(null, "", `?${writeDirectoryState(state)}`);
      void load();
    });
  });
  pageSize.addEventListener("change", () => applyFilters());
  window.addEventListener("popstate", () => {
    state = readDirectoryState(new URL(window.location.href).searchParams);
    syncControls();
    void load();
  });

  await load();
}

if (document.querySelector("[data-directory-app]")) {
  void mountDirectory();
}
