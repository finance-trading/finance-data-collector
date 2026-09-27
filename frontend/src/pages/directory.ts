import { apiGet } from "../api/client";
import type {
  CatalogLayerListView,
  CompanyDirectoryItem,
  CompanyDirectoryView,
  IngestionStatus,
} from "../api/types";
import { renderDataState } from "../components/data-state";
import { renderPagination } from "../components/pagination";

export interface DirectoryState {
  query: string;
  layer: string;
  segment: string;
  status: "" | IngestionStatus;
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

export function readDirectoryState(search: URLSearchParams): DirectoryState {
  const rawStatus = search.get("status") ?? "";
  const rawPage = Number(search.get("page") ?? "1");
  const rawPageSize = Number(search.get("pageSize") ?? "25");
  return {
    query: search.get("query")?.trim() ?? "",
    layer: search.get("layer") ?? "",
    segment: search.get("segment") ?? "",
    status: statuses.has(rawStatus as IngestionStatus)
      ? (rawStatus as IngestionStatus)
      : "",
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

function cell(label: string, className = ""): HTMLTableCellElement {
  const element = document.createElement("td");
  element.dataset.label = label;
  element.className = className;
  return element;
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
    const identity = company.research_available
      ? document.createElement("a")
      : document.createElement("div");
    identity.className = "company-identity";
    if (identity instanceof HTMLAnchorElement) {
      identity.href = `company.html?ticker=${encodeURIComponent(company.ticker)}`;
    }
    const ticker = document.createElement("strong");
    ticker.textContent = company.ticker;
    const name = document.createElement("span");
    name.textContent = company.name;
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

    const actionCell = cell("Action", "action-cell");
    if (company.research_available) {
      const action = document.createElement("a");
      action.href = `company.html?ticker=${encodeURIComponent(company.ticker)}`;
      action.setAttribute("aria-label", `Open ${company.ticker} research`);
      action.textContent = "Open";
      actionCell.append(action);
    } else {
      const unavailable = document.createElement("span");
      unavailable.className = "availability availability-missing";
      unavailable.textContent = "Not ingested";
      actionCell.append(unavailable);
    }

    row.append(companyCell, categoryCell, dateCell, statusCell, countCell, actionCell);
    target.append(row);
  });
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
  let state = readDirectoryState(new URL(window.location.href).searchParams);
  let controller: AbortController | null = null;
  let layers: CatalogLayerListView | null = null;

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
  syncControls();

  const applyFilters = (openExact = false): void => {
    state = {
      query: query.value.trim(),
      layer: layer.value,
      segment: segment.value,
      status: status.value as DirectoryState["status"],
      page: 1,
      pageSize: Number(pageSize.value) as DirectoryState["pageSize"],
    };
    updateSegments();
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
