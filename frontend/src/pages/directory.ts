import { apiGet, apiPost } from "../api/client";
import type {
  CatalogLayerListView,
  CompanyDirectoryItem,
  CompanyDirectoryView,
  IngestionStatus,
  QuotesPayload,
} from "../api/types";
import { renderDataState } from "../components/data-state";
import { renderPagination } from "../components/pagination";

export type DirectorySortKey =
  | "market_cap"
  | "change_pct"
  | "week_change_pct"
  | "change_52w_pct";

export type DirectorySort = `${DirectorySortKey}_${"desc" | "asc"}`;

export interface DirectoryState {
  query: string;
  layer: string;
  segment: string;
  status: "" | IngestionStatus;
  sort: "" | DirectorySort;
  page: number;
  pageSize: 25 | 50 | 100;
}

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
  "change_52w_pct_desc",
  "change_52w_pct_asc",
]);

export function readDirectoryState(search: URLSearchParams): DirectoryState {
  const rawStatus = search.get("status") ?? "";
  const rawSort = search.get("sort") ?? "";
  const rawPage = Number(search.get("page") ?? "1");
  const rawPageSize = Number(search.get("pageSize") ?? "25");
  return {
    query: search.get("query")?.trim() ?? "",
    layer: search.get("layer") ?? "",
    segment: search.get("segment") ?? "",
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
  if (state.layer) params.set("layer", state.layer);
  if (state.segment) params.set("segment", state.segment);
  if (state.status) params.set("status", state.status);
  if (state.sort) params.set("sort", state.sort);
  params.set("page", String(state.page));
  params.set("pageSize", String(state.pageSize));
  return params;
}

const statusLabels: Record<IngestionStatus, string> = {
  parsed: "Parsed",
  failed: "Parse failed",
  unavailable: "Unavailable",
  not_ingested: "Not ingested",
};

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

function formatCompactUSD(value: number): string {
  if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
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

    const dateCell = cell("Latest filing", "date-cell");
    dateCell.textContent = formatDate(company.latest_filing_date);

    const statusCell = cell("Coverage");
    const badge = document.createElement("span");
    badge.className = `parse-status status-${company.ingestion_status}`;
    badge.textContent = statusLabels[company.ingestion_status];
    statusCell.append(badge);

    const countCell = cell("Filings", "number-column");
    countCell.textContent = new Intl.NumberFormat("en").format(company.filing_count);

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
      cap.textContent = formatCompactUSD(company.market_cap);
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
      // Coverage already reports "Not ingested"; do not shout it twice.
      const unavailable = document.createElement("span");
      unavailable.className = "availability availability-missing";
      unavailable.textContent = "—";
      actionCell.append(unavailable);
    }

    row.append(
      companyCell,
      categoryCell,
      dateCell,
      statusCell,
      countCell,
      priceCell,
      changeCell("1W", "week", company.week_change_pct),
      changeCell("52W", "year", company.change_52w_pct),
      capCell,
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

function changeCell(
  label: string,
  className: string,
  pct: number | null | undefined,
): HTMLTableCellElement {
  const element = cell(label, `number-column change-cell ${className}-cell`);
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
  const layer = document.querySelector<HTMLSelectElement>("#layer-filter")!;
  const segment = document.querySelector<HTMLSelectElement>("#segment-filter")!;
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
        `Price, 1W, 52W and market cap as of ${formatDate(quoteAsOfDate)} close.`,
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
    const currentLayer = layers?.layers.find((item) => item.id === state.layer);
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
    layer.value = state.layer;
    status.value = state.status;
    pageSize.value = String(state.pageSize);
    updateSegments();
    syncSortHeaders(state.sort);
  };

  const load = async (openExact = false): Promise<void> => {
    controller?.abort();
    controller = new AbortController();
    const request = controller;
    renderDataState(directoryState, "loading", "Reading the AI company catalog…");
    const params = new URLSearchParams();
    if (state.query) params.set("query", state.query);
    if (state.layer) params.set("layer", state.layer);
    if (state.segment) params.set("segment", state.segment);
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
      const exact = payload.companies.find(
        (company) => company.ticker === state.query.toUpperCase(),
      );
      if (openExact && exact?.research_available) {
        window.location.assign(
          `company.html?ticker=${encodeURIComponent(exact.ticker)}`,
        );
        return;
      }
      renderCompanies(payload.companies);
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
    layers.layers.forEach((item) =>
      layer.append(option(item.id, `${item.name} (${item.count})`)),
    );
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

  const applyFilters = (openExact = false): void => {
    state = {
      ...state,
      query: query.value.trim(),
      layer: layer.value,
      segment: segment.value,
      status: status.value as DirectoryState["status"],
      page: 1,
      pageSize: Number(pageSize.value) as DirectoryState["pageSize"],
    };
    updateSegments();
    syncSortHeaders(state.sort);
    history.replaceState(null, "", `?${writeDirectoryState(state)}`);
    void load(openExact);
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    applyFilters(true);
  });
  query.addEventListener("search", () => applyFilters());
  layer.addEventListener("change", () => {
    state.layer = layer.value;
    state.segment = "";
    updateSegments();
    applyFilters();
  });
  segment.addEventListener("change", () => applyFilters());
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
