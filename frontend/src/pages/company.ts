import { ApiError, apiGet } from "../api/client";
import type {
  CompanyView,
  EvidenceView,
  FactItem,
  FactView,
  FilingListView,
  FilingSummary,
  FilingView,
  SectionView,
  StatementLine,
  StatementView,
  TableItem,
  TableView,
} from "../api/types";
import { markCurrentNav } from "../components/site-shell";

const API_COMPANIES = "/api/v1/companies/";
const API_FILINGS = "/api/v1/filings/";

interface RequestToken {
  accession: string;
  sequence: number;
}

interface ApiDetail {
  status?: string;
  message?: string;
}

interface PageState {
  ticker: string;
  filings: FilingSummary[];
  selectedAccession: string;
  requestSequence: number;
}

const pageState: PageState = {
  ticker: "",
  filings: [],
  selectedAccession: "",
  requestSequence: 0,
};

const statementRequests = [
  {type: "IncomeStatement", panelId: "income-statement"},
  {type: "BalanceSheet", panelId: "balance-sheet"},
  {type: "CashFlowStatement", panelId: "cash-flow"},
] as const;

export function readTicker(url: URL): string | null {
  const ticker = url.searchParams.get("ticker")?.trim() ?? "";
  return /^[A-Za-z0-9.-]{1,10}$/.test(ticker) ? ticker.toUpperCase() : null;
}

export function companyStatusLabel(status: number | string | null): string {
  if (status === 404 || status === "not_found") return "Not found";
  if (status === 422 || status === "failed") return "Parse failed";
  if (status === "unsupported") return "Unsupported";
  if (status === "success" || status === "parsed") return "Parsed";
  return "Unavailable";
}

export function createCompanyState() {
  let accession = "";
  let sequence = 0;
  return {
    selectFiling(next: string): void {
      accession = next;
      sequence += 1;
    },
    beginEvidence(selected: string): RequestToken {
      return {accession: selected, sequence};
    },
    acceptEvidence(token: RequestToken): boolean {
      return token.accession === accession && token.sequence === sequence;
    },
  };
}

const requestState = createCompanyState();

export function loadCompany(ticker: string, signal?: AbortSignal): Promise<CompanyView> {
  return apiGet<CompanyView>(
    `${API_COMPANIES}${encodeURIComponent(ticker)}`,
    new URLSearchParams(),
    signal,
  );
}

export function loadFiling(accession: string, signal?: AbortSignal): Promise<FilingView> {
  return apiGet<FilingView>(
    `${API_FILINGS}${encodeURIComponent(accession)}`,
    new URLSearchParams(),
    signal,
  );
}

export async function selectEvidence(
  accession: string,
  evidenceId: string,
  token: RequestToken,
): Promise<EvidenceView | null> {
  const evidence = await apiGet<EvidenceView>(
    `${API_FILINGS}${encodeURIComponent(accession)}/evidence/${encodeURIComponent(evidenceId)}`,
  );
  return requestState.acceptEvidence(token) ? evidence : null;
}

function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing #${id}`);
  return element as T;
}

function textElement<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  value: unknown,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null || value === "" ? "—" : String(value);
  return node;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

function detailFor(error: unknown): ApiDetail {
  if (!(error instanceof ApiError) || !error.detail || typeof error.detail !== "object") {
    return {};
  }
  const payload = error.detail as {detail?: ApiDetail};
  return payload.detail ?? {};
}

function statusKey(error: unknown): string {
  const detail = detailFor(error);
  if (detail.status) return detail.status;
  if (error instanceof ApiError && error.status === 404) return "not_found";
  if (error instanceof ApiError && error.status === 422) return "failed";
  return "unavailable";
}

function stateClass(status: string | null): string {
  if (status === "not_found") return "not-found";
  if (status === "success" || status === "parsed") return "success";
  if (status === "failed" || status === "unsupported") return status;
  return "unavailable";
}

function statusMessage(error: unknown, context: string) {
  const key = statusKey(error);
  const label = companyStatusLabel(key);
  const detail = detailFor(error);
  return {
    label,
    className: stateClass(key),
    text: `${label}: ${detail.message ?? `${context} could not be loaded.`}`,
  };
}

function stateNode(message: string, className = ""): HTMLParagraphElement {
  const node = textElement("p", `state-message ${className}`.trim(), message);
  node.setAttribute("role", className === "failed" ? "alert" : "status");
  return node;
}

/* ---- Full-text modal ------------------------------------------------ */
/*
 * Parsed disclosure prose runs several pages. It is displayed truncated in
 * place, with the complete text opened in a modal on demand. The dialog is
 * toggled by class instead of showModal() so the same code path runs in a
 * browser and in jsdom, which has no modal support.
 */

const FULL_TEXT_THRESHOLD = 900;
const FULL_TEXT_TRUNCATION = 420;
const FULL_TEXT_ELLIPSIS = "…";

// Narrative fact values sit in a narrow grid column, so they collapse earlier
// than the full-width disclosure prose.
const FACT_VALUE_THRESHOLD = 160;
const FACT_VALUE_TRUNCATION = 140;

function fullTextDialog(): HTMLElement {
  return byId("full-text");
}

function openFullText(body: HTMLElement, label: string): void {
  const dialog = fullTextDialog();
  byId("full-text-title").textContent = label;
  const bodyView = byId("full-text-body");
  bodyView.textContent = body.getAttribute("data-full-text") || body.textContent || "—";
  bodyView.setAttribute("aria-label", `${label} full text`);
  dialog.classList.add("is-open");
  dialog.setAttribute("aria-hidden", "false");
  dialog.querySelector<HTMLElement>("#full-text-close")?.focus();
}

function closeFullText(): void {
  const dialog = fullTextDialog();
  if (!dialog.classList.contains("is-open")) return;
  dialog.classList.remove("is-open");
  dialog.setAttribute("aria-hidden", "true");
  dialog.querySelector<HTMLElement>("#full-text-body")?.replaceChildren();
}

export function initializeFullTextModal(): void {
  const dialog = fullTextDialog();
  dialog.querySelector<HTMLElement>("#full-text-close")?.addEventListener("click", closeFullText);
  dialog.addEventListener("click", (event) => {
    // Only a click on the panel's own padding counts as a dismissal, not on
    // the header or body controls.
    if (event.target === dialog) closeFullText();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeFullText();
  });
}

/** Cut at a word boundary so the displayed excerpt never ends mid-token. */
function truncateProse(prose: string, limit: number): string {
  const slice = prose.slice(0, limit);
  const cut = slice.lastIndexOf(" ");
  return `${slice.slice(0, cut > 0 ? cut : limit)}${FULL_TEXT_ELLIPSIS}`;
}

function fullTextTrigger(body: HTMLElement, label: string, count: number): HTMLButtonElement {
  const button = textElement("button", "expand-text", `Full text (${count.toLocaleString("en-US")} characters)`);
  button.type = "button";
  button.addEventListener("click", () => openFullText(body, label));
  return button;
}

interface DisclosureOptions {
  threshold?: number;
  truncation?: number;
}

/**
 * Render prose truncated in place with a button for the complete text. The
 * full text is kept on the element rather than in the DOM (where the button's
 * own text would pollute `textContent`), so the modal shows exactly what was
 * parsed. Short prose is returned unchanged — there is nothing to expand.
 */
export function disclosureBody(
  text: unknown,
  label: string,
  options: DisclosureOptions = {},
): HTMLElement {
  const threshold = options.threshold ?? FULL_TEXT_THRESHOLD;
  const truncation = options.truncation ?? FULL_TEXT_TRUNCATION;
  const body = textElement("p", "disclosure-copy", text);
  body.setAttribute("aria-label", label);
  const prose = body.textContent || "";
  if (prose.length <= threshold) return body;
  body.setAttribute("data-full-text", prose);
  body.classList.add("is-truncated");
  body.replaceChildren(
    document.createTextNode(truncateProse(prose, truncation)),
    fullTextTrigger(body, label, prose.length),
  );
  return body;
}

function setCompanyFailure(error: unknown): void {
  const message = statusMessage(error, "Company record");
  byId("company-name").textContent = "Company unavailable";
  byId("company-identity").textContent = message.text;
  const status = byId("company-status");
  status.textContent = message.label;
  status.className = `status status-${message.className}`;
  byId("filings").replaceChildren(stateNode(message.text, message.className));
}

function renderCompany(company: CompanyView): void {
  document.title = `${company.ticker} filings | Finance Data Collector`;
  byId("company-name").textContent = company.name;
  byId("company-identity").textContent = [
    company.ticker,
    `CIK ${company.cik}`,
    company.sic ? `SIC ${company.sic}` : "SIC unavailable",
  ].join("  /  ");
  byId("filing-count").textContent = `${company.filing_count} filings`;
  const status = byId("company-status");
  status.textContent = companyStatusLabel(company.latest_filing_status);
  status.className = `status status-${stateClass(company.latest_filing_status)}`;
}

function filingButton(filing: FilingSummary): HTMLButtonElement {
  const button = document.createElement("button");
  button.className = "filing-choice";
  button.type = "button";
  button.dataset.accession = filing.accession;
  button.setAttribute(
    "aria-label",
    `${filing.form} filed ${formatDate(filing.filing_date)}, ${companyStatusLabel(filing.status)}`,
  );
  if (filing.accession === pageState.selectedAccession) {
    button.setAttribute("aria-current", "true");
  }
  button.append(
    textElement("span", "filing-form", filing.form),
    textElement(
      "span",
      `filing-state ${stateClass(filing.status)}`,
      companyStatusLabel(filing.status),
    ),
    textElement("span", "filing-date", formatDate(filing.filing_date)),
    textElement("span", "filing-accession", filing.accession),
  );
  button.addEventListener("click", () => void selectFiling(filing));
  return button;
}

function renderFilings(filings: FilingSummary[]): void {
  pageState.filings = filings;
  const navigation = byId("filings");
  if (!filings.length) {
    navigation.replaceChildren(
      stateNode("Unavailable: no filings match this filter.", "unavailable"),
    );
    return;
  }
  navigation.replaceChildren(...filings.map(filingButton));
}

function updateSelectedSummary(filing: FilingSummary): void {
  byId("filing-kicker").textContent = `${filing.form} filing`;
  byId("filing-title").textContent = filing.report_date
    ? `Period ended ${formatDate(filing.report_date)}`
    : "Filing details";
  byId("selected-accession").textContent = filing.accession;
  byId("selected-filing-date").textContent = formatDate(filing.filing_date);
  byId("selected-report-date").textContent = formatDate(filing.report_date);
  byId("selected-status").textContent = companyStatusLabel(filing.status);
  renderFilings(pageState.filings);
}

function updateFilingDetail(detail: FilingView): void {
  byId("filing-kicker").textContent = `${detail.form}${detail.is_amended ? "/A" : ""} filing`;
  byId("filing-title").textContent = detail.report_date
    ? `Period ended ${formatDate(detail.report_date)}`
    : "Filing details";
  byId("selected-filing-date").textContent = formatDate(detail.filing_date);
  byId("selected-report-date").textContent = formatDate(detail.report_date);
  byId("selected-status").textContent = companyStatusLabel(detail.parse.status);
  const source = byId<HTMLAnchorElement>("sec-filing-link");
  if (detail.sec_url) {
    source.href = detail.sec_url;
    source.classList.remove("is-hidden");
  } else {
    source.classList.add("is-hidden");
    source.removeAttribute("href");
  }
}

function evidenceButton(evidence: EvidenceView | null, label = "View evidence") {
  const button = textElement("button", "evidence-button", label);
  button.type = "button";
  if (!evidence?.evidence_id) {
    button.disabled = true;
    button.textContent = "Unavailable";
    return button;
  }
  button.addEventListener("click", () => void openEvidence(evidence));
  return button;
}

function evidenceDefinition(term: string, value: string | null): HTMLDivElement {
  const wrapper = document.createElement("div");
  wrapper.append(
    textElement("dt", "", term),
    textElement("dd", "", value || "Unavailable"),
  );
  return wrapper;
}

function renderEvidence(evidence: EvidenceView): void {
  const record = document.createElement("article");
  record.className = "evidence-record";
  record.append(
    textElement("h3", "", evidence.locator_value || "Filing source"),
    textElement("p", "filing-accession", evidence.accession),
  );
  const details = document.createElement("dl");
  details.append(
    evidenceDefinition("Locator type", evidence.locator_type),
    evidenceDefinition("Artifact", evidence.relative_path),
    evidenceDefinition("Content SHA-256", evidence.content_sha256),
  );
  record.append(details);
  if (evidence.excerpt) {
    record.append(disclosureBody(evidence.excerpt, "Evidence excerpt"));
  } else {
    record.append(stateNode("Unavailable: no excerpt was stored.", "unavailable"));
  }
  if (evidence.accession_url) {
    const link = textElement("a", "source-link", "Open exact SEC source");
    link.href = evidence.accession_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    record.append(link);
  }
  byId("evidence-content").replaceChildren(record);
}

async function openEvidence(embedded: EvidenceView): Promise<void> {
  const token = requestState.beginEvidence(embedded.accession);
  renderEvidence(embedded);
  byId("evidence").scrollIntoView({behavior: "smooth", block: "start"});
  try {
    const evidence = await selectEvidence(
      embedded.accession,
      embedded.evidence_id,
      token,
    );
    if (evidence) renderEvidence(evidence);
  } catch (error) {
    if (!requestState.acceptEvidence(token)) return;
    const message = statusMessage(error, "Evidence");
    byId("evidence-content").replaceChildren(
      stateNode(message.text, message.className),
    );
  }
}

function reportedValue(item: FactItem | StatementLine): string {
  const value = item.value_numeric ?? item.value_text;
  if (value == null || value === "") return "Unavailable";
  return item.unit ? `${value} ${item.unit}` : String(value);
}

/**
 * Render a reported fact value. Numeric values stay a compact right-aligned
 * span; narrative values (e.g. TextBlock facts) are truncated in place and
 * opened in the full-text modal, like disclosure prose.
 */
function factValue(fact: FactItem): HTMLElement {
  const value = reportedValue(fact);
  if (fact.value_numeric != null || value.length <= FACT_VALUE_THRESHOLD) {
    return textElement("span", "fact-value", value);
  }
  return disclosureBody(value, "Reported value", {
    threshold: FACT_VALUE_THRESHOLD,
    truncation: FACT_VALUE_TRUNCATION,
  });
}

function renderFacts(result: FactView): void {
  const chart = byId("fact-chart");
  if (!result.facts.length) {
    chart.replaceChildren(stateNode("Unavailable: no facts were returned.", "unavailable"));
    return;
  }
  const visible = result.facts.slice(0, 8);
  const magnitudes = visible.map((fact) => Math.abs(Number(fact.value_numeric)) || 0);
  const maximum = Math.max(...magnitudes, 1);
  chart.replaceChildren(
    ...visible.map((fact, index) => {
      const row = document.createElement("div");
      row.className = "fact-row";
      const period = [formatDate(fact.end_date), fact.period_type]
        .filter((part) => part && part !== "—")
        .join(" / ");
      const track = document.createElement("span");
      track.className = "period-track";
      track.setAttribute("aria-hidden", "true");
      const bar = document.createElement("span");
      bar.className = "period-bar";
      bar.style.width = `${Math.max(3, (magnitudes[index] / maximum) * 100)}%`;
      track.append(bar);
      row.append(
        textElement("span", "fact-label", fact.label || fact.concept),
        track,
        textElement("span", "fact-period", period || "Unavailable"),
        factValue(fact),
        evidenceButton(fact.evidence, "Source"),
      );
      return row;
    }),
  );
}

function statementStateRow(message: string, className: string): HTMLTableRowElement {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = 4;
  cell.append(stateNode(message, className));
  row.append(cell);
  return row;
}

function statementBody(panelId: string): HTMLTableSectionElement {
  const body = byId(panelId).querySelector<HTMLTableSectionElement>("tbody");
  if (!body) throw new Error(`Missing statement body for ${panelId}`);
  return body;
}

function renderStatement(panelId: string, result: StatementView): void {
  const body = statementBody(panelId);
  if (!result.lines.length) {
    body.replaceChildren(
      statementStateRow("Unavailable: no statement lines were returned.", "unavailable"),
    );
    return;
  }
  body.replaceChildren(
    ...result.lines.map((line) => {
      const row = document.createElement("tr");
      const labelCell = document.createElement("td");
      const label = textElement("span", "line-label", line.label || line.concept);
      label.style.setProperty("--depth", String(Math.min(Math.max(line.depth || 0, 0), 6)));
      const period = [formatDate(line.end_date), line.period_type]
        .filter((part) => part && part !== "—")
        .join(" / ");
      labelCell.append(
        label,
        textElement("span", "line-period-mobile", `Period: ${period || "Unavailable"}`),
      );
      const evidenceCell = document.createElement("td");
      evidenceCell.append(evidenceButton(line.evidence, "Source"));
      row.append(
        labelCell,
        textElement("td", "", period || "Unavailable"),
        textElement("td", "", reportedValue(line)),
        evidenceCell,
      );
      return row;
    }),
  );
}

function renderRequestFailure(target: HTMLElement, error: unknown, context: string): void {
  const message = statusMessage(error, context);
  target.replaceChildren(stateNode(message.text, message.className));
}

function renderSection(section: SectionView): void {
  const article = byId("section-result");
  const heading = textElement("h4", "", section.heading || "Management discussion");
  heading.id = "section-title";
  article.replaceChildren(
    heading,
    disclosureBody(section.text || "Unavailable: section text is empty.", "Management discussion"),
    evidenceButton(section.evidence, "View section source"),
  );
}

function tableDescription(table: TableItem): string {
  return `${table.rows?.length ?? 0} rows, ${table.columns?.length ?? 0} columns, ${
    table.confidence == null ? "confidence unavailable" : `confidence ${table.confidence}`
  }`;
}

function renderTables(result: TableView): void {
  const article = byId("table-result");
  const heading = textElement("h4", "", "Extracted tables");
  heading.id = "table-title";
  if (!result.tables.length) {
    article.replaceChildren(
      heading,
      stateNode("Unavailable: no tables were returned.", "unavailable"),
    );
    return;
  }
  const list = document.createElement("div");
  result.tables.forEach((table) => {
    const entry = document.createElement("section");
    entry.append(
      textElement("h4", "", table.caption || table.table_type),
      textElement("p", "table-summary", tableDescription(table)),
      evidenceButton(table.evidence, "View table source"),
    );
    list.append(entry);
  });
  article.replaceChildren(heading, list);
}

function resetWorkspaceLoading(): void {
  byId("fact-chart").replaceChildren(stateNode("Loading reported facts…"));
  statementRequests.forEach((request) => {
    statementBody(request.panelId).replaceChildren(statementStateRow("Loading statement…", ""));
  });
  const sectionHeading = textElement("h4", "", "Management discussion");
  sectionHeading.id = "section-title";
  byId("section-result").replaceChildren(sectionHeading, stateNode("Loading section…"));
  const tableHeading = textElement("h4", "", "Extracted tables");
  tableHeading.id = "table-title";
  byId("table-result").replaceChildren(tableHeading, stateNode("Loading tables…"));
  byId("evidence-content").replaceChildren(
    textElement(
      "p",
      "evidence-empty",
      "Choose a source link beside a reported value to inspect its exact filing locator, excerpt, and content hash.",
    ),
  );
}

async function selectFiling(filing: FilingSummary): Promise<void> {
  pageState.selectedAccession = filing.accession;
  pageState.requestSequence += 1;
  const sequence = pageState.requestSequence;
  requestState.selectFiling(filing.accession);
  updateSelectedSummary(filing);
  resetWorkspaceLoading();
  const accession = encodeURIComponent(filing.accession);
  const base = `${API_FILINGS}${accession}`;
  const statementPromises = statementRequests.map((request) =>
    apiGet<StatementView>(
      `${base}/statements`,
      new URLSearchParams({statement_type: request.type}),
    ),
  );
  const settled = await Promise.allSettled([
    loadFiling(filing.accession),
    apiGet<FactView>(`${base}/facts`),
    apiGet<SectionView>(`${base}/sections/md_and_a`),
    apiGet<TableView>(`${base}/tables`),
    ...statementPromises,
  ]);
  if (sequence !== pageState.requestSequence) return;
  const [detail, facts, section, tables, ...statements] = settled;

  if (detail.status === "fulfilled") updateFilingDetail(detail.value as FilingView);
  else {
    const message = statusMessage(detail.reason, "Filing details");
    byId("selected-status").textContent = message.label;
    byId("sec-filing-link").classList.add("is-hidden");
  }
  if (facts.status === "fulfilled") renderFacts(facts.value as FactView);
  else renderRequestFailure(byId("fact-chart"), facts.reason, "Reported facts");
  if (section.status === "fulfilled") renderSection(section.value as SectionView);
  else renderRequestFailure(byId("section-result"), section.reason, "Management discussion");
  if (tables.status === "fulfilled") renderTables(tables.value as TableView);
  else renderRequestFailure(byId("table-result"), tables.reason, "Extracted tables");

  statements.forEach((result, index) => {
    const body = statementBody(statementRequests[index].panelId);
    if (result.status === "fulfilled") {
      renderStatement(statementRequests[index].panelId, result.value as StatementView);
    } else {
      renderRequestFailure(body, result.reason, "Statement");
    }
  });
}

async function loadFilings(form = ""): Promise<void> {
  const params = new URLSearchParams();
  if (form) params.set("form", form);
  try {
    const result = await apiGet<FilingListView>(
      `${API_COMPANIES}${encodeURIComponent(pageState.ticker)}/filings`,
      params,
    );
    renderFilings(result.filings);
    if (result.filings.length) {
      const current = result.filings.find(
        (filing) => filing.accession === pageState.selectedAccession,
      );
      await selectFiling(current ?? result.filings[0]);
    }
  } catch (error) {
    renderRequestFailure(byId("filings"), error, "Filings");
  }
}

function activateTab(tab: HTMLElement): void {
  const tabs = [...document.querySelectorAll<HTMLElement>('[role="tab"]')];
  tabs.forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute("aria-selected", String(selected));
    candidate.tabIndex = selected ? 0 : -1;
    const panel = candidate.dataset.panel;
    if (panel) byId(panel).hidden = !selected;
  });
  tab.focus();
}

function initializeTabs(): void {
  const tabs = [...document.querySelectorAll<HTMLElement>('[role="tab"]')];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateTab(tab));
    tab.addEventListener("keydown", (event) => {
      if (!(event instanceof KeyboardEvent)) return;
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let target = index;
      if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = tabs.length - 1;
      activateTab(tabs[target]);
    });
  });
}

export async function mountCompanyPage(): Promise<void> {
  markCurrentNav(window.location.pathname);
  initializeTabs();
  initializeFullTextModal();
  const ticker = readTicker(new URL(window.location.href));
  if (!ticker) {
    setCompanyFailure(
      new ApiError(400, {
        detail: {status: "unavailable", message: "Add a valid ticker query parameter."},
      }),
    );
    return;
  }
  pageState.ticker = ticker;
  byId<HTMLSelectElement>("form-filter").addEventListener("change", (event) => {
    void loadFilings((event.currentTarget as HTMLSelectElement).value);
  });
  try {
    renderCompany(await loadCompany(ticker));
    await loadFilings();
  } catch (error) {
    setCompanyFailure(error);
  }
}

if (document.querySelector("[data-company-app]")) {
  void mountCompanyPage();
}
