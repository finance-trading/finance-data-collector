import { ApiError, apiGet } from "../api/client";
import type { AnalystOpinionsView, AnalystFirmView, QualityScoreView } from "../api/types";
import { markCurrentNav } from "../components/site-shell";

const API_QUALITY = "/api/v1/companies/";
const QUALITY_PATH = "/quality-score";

export function readTicker(url: URL): string | null {
  const ticker = url.searchParams.get("ticker")?.trim() ?? "";
  return /^[A-Za-z0-9.-]{1,10}$/.test(ticker) ? ticker.toUpperCase() : null;
}

export function qualityScoreStateLabel(status: string): string {
  switch (status) {
    case "QUALIFIED": return "Qualified";
    case "NOT_QUALIFIED": return "Not qualified";
    case "SEPARATE_MODEL": return "Separate model";
    default: return "Unknown";
  }
}

export async function loadQualityScore(ticker: string): Promise<QualityScoreView | null> {
  try {
    return await apiGet<QualityScoreView>(
      `${API_QUALITY}${encodeURIComponent(ticker.trim().toUpperCase())}${QUALITY_PATH}`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const ANALYST_PATH = "/analyst-opinions";
const EMPTY_ANALYST = "No recent firm-level analyst opinions in the last 24 months.";

export async function loadAnalystOpinions(ticker: string): Promise<AnalystOpinionsView | null> {
  try {
    return await apiGet<AnalystOpinionsView>(
      `${API_QUALITY}${encodeURIComponent(ticker.trim().toUpperCase())}${ANALYST_PATH}`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

function formatTarget(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function firmActionLabel(firm: AnalystFirmView): string {
  const bits: string[] = [];
  if (firm.action) bits.push(firm.action);
  if (firm.target_action) bits.push(firm.target_action);
  return bits.length ? bits.join(" · ") : "—";
}

function ratingCell(firm: AnalystFirmView): HTMLElement {
  const element = document.createElement("td");
  element.className = "analyst-rating-cell";
  if (firm.rating) {
    const badge = document.createElement("span");
    badge.className = `analyst-rating analyst-rating--${firm.rating}`;
    badge.textContent = firm.rating;
    element.append(badge);
    if (firm.to_grade && firm.to_grade.toLowerCase() !== firm.rating) {
      const grade = document.createElement("span");
      grade.className = "analyst-grade";
      grade.textContent = ` (${firm.to_grade})`;
      element.append(grade);
    }
  } else {
    element.append(textElement("span", "", "—"));
  }
  return element;
}

export function renderAnalystOpinions(view: AnalystOpinionsView | null): void {
  const summary = byId<HTMLParagraphElement>("analyst-opinions-summary");
  const body = byId<HTMLTableSectionElement>("analyst-opinions-body");
  body.replaceChildren();

  if (!view || view.firms.length === 0) {
    summary.textContent = EMPTY_ANALYST;
    const emptyRow = document.createElement("tr");
    emptyRow.append(textElement("td", "analyst-empty", EMPTY_ANALYST));
    emptyRow.firstElementChild?.setAttribute("colspan", "6");
    body.append(emptyRow);
    return;
  }

  const parts: string[] = [];
  if (view.mean_target != null) parts.push(`Mean target ${formatTarget(view.mean_target)}`);
  parts.push(`${view.firm_count} firm${view.firm_count === 1 ? "" : "s"}`);
  if (view.rating_skew) parts.push(`${view.rating_skew} skew`);
  summary.textContent = parts.join(" · ");

  for (const firm of view.firms) {
    const row = document.createElement("tr");
    if (!firm.in_window) row.className = "analyst-row is-out-of-window";
    row.append(
      textElement("td", "analyst-firm", firm.firm),
      ratingCell(firm),
      textElement("td", "analyst-target", formatTarget(firm.target)),
      textElement("td", "analyst-target", formatTarget(firm.prior_target)),
      textElement("td", "analyst-action", firmActionLabel(firm)),
      textElement("td", "analyst-date", formatDate(firm.action_at)),
    );
    body.append(row);
  }
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

function stateMessage(message: string, className = ""): HTMLParagraphElement {
  const node = textElement("p", `state-message ${className}`.trim(), message);
  node.setAttribute("role", className === "unavailable" ? "alert" : "status");
  return node;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value.includes("T") ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

function qualityNumber(value: string | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(2);
}

function yearCount(value: number | null): string {
  return value == null ? "—" : `${value} years`;
}

function compactUsd(value: string | null): string {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function reasonLabel(value: string): string {
  const words = value.replaceAll("_", " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : value;
}

function statusClass(score: QualityScoreView | null, error?: string): string {
  if (error || !score) return "status-unavailable";
  switch (score.status) {
    case "QUALIFIED": return "status-qualified";
    case "NOT_QUALIFIED": return "status-not-qualified";
    case "SEPARATE_MODEL": return "status-separate-model";
    default: return "status-unknown";
  }
}

function renderHeader(score: QualityScoreView | null, ticker: string, error?: string): void {
  const name = score?.company_name || ticker || "Company";
  document.title = `${name} quality | Finance Data Collector`;
  byId("company-name").textContent = name;

  const identity = score
    ? [score.ticker, score.sector ?? "Sector unavailable", `Rating cutoff ${formatDate(score.rating_cutoff)}`]
    : [ticker || "No ticker", "Quality score unavailable"];
  byId("company-identity").textContent = identity.join("  /  ");

  const status = byId("company-status");
  status.textContent = error || !score ? "Unavailable" : qualityScoreStateLabel(score.status);
  status.className = `status ${statusClass(score, error)}`;
}

function renderSummary(score: QualityScoreView | null, error?: string): void {
  const body = byId("quality-score-body");
  body.setAttribute("role", error ? "alert" : "status");
  if (error) {
    body.replaceChildren(stateMessage(error, "unavailable"));
    return;
  }
  if (!score) {
    body.replaceChildren(stateMessage("No score record is available for this company."));
    return;
  }

  const value = score.score_available ? qualityNumber(score.quality_score) : "—";
  const figure = document.createElement("div");
  figure.className = "score-figure";
  figure.append(
    textElement("strong", "score-value", value),
    textElement("span", "score-status", qualityScoreStateLabel(score.status)),
  );
  const meta = textElement(
    "p",
    "score-meta",
    `Rating cutoff ${formatDate(score.rating_cutoff)} · Calculated ${formatDate(score.calculated_at)}`,
  );
  body.replaceChildren(figure, meta);
}

function renderDimensions(score: QualityScoreView | null): void {
  const grid = byId("quality-dimensions");
  if (!score) {
    grid.replaceChildren(stateMessage("No dimension details available."));
    return;
  }

  const dimensions: Array<[string, string | null]> = [
    ["Revenue growth", score.revenue_growth_dimension],
    ["Operating margin", score.operating_margin_dimension],
    ["Cash conversion", score.cash_conversion_dimension],
    ["Capital efficiency", score.capital_efficiency_dimension],
    ["Financial strength", score.financial_strength_dimension],
  ];
  const cards = dimensions.map(([label, value]) => {
    const card = document.createElement("div");
    card.className = "dimension";
    card.append(
      textElement("span", "dimension-label", label),
      textElement("strong", "dimension-value", qualityNumber(value)),
    );
    return card;
  });
  grid.replaceChildren(...cards);
}

function renderStrength(score: QualityScoreView | null): void {
  const grid = byId("financial-strength");
  if (!score) {
    grid.replaceChildren(stateMessage("No financial-strength details available."));
    return;
  }

  const rows: Array<[string, string]> = [
    ["Hard status", qualityScoreStateLabel(score.v2_hard_status ?? "UNKNOWN")],
    [
      "Hard gates",
      `${score.v2_hard_gate_count ?? "—"} / ${score.v2_hard_gate_total ?? "—"}`,
    ],
    ["Net debt / EBITDA", qualityNumber(score.v2_net_debt_ebitda)],
    ["Interest coverage", qualityNumber(score.v2_interest_coverage)],
    ["Cumulative net income", compactUsd(score.v2_cumulative_net_income)],
    ["Cumulative operating cash flow", compactUsd(score.v2_cumulative_cfo)],
    ["Positive operating income years", yearCount(score.v2_positive_operating_income_years)],
    ["Positive cash flow years", yearCount(score.v2_positive_cfo_years)],
  ];
  const list = document.createElement("dl");
  list.className = "metric-list";
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "metric";
    row.append(textElement("dt", "", label), textElement("dd", "", value));
    list.append(row);
  }
  grid.replaceChildren(list);
}

function renderNotes(score: QualityScoreView | null): void {
  const notes = byId("quality-notes");
  if (!score) {
    notes.replaceChildren(stateMessage("No scoring notes available."));
    return;
  }

  const reasons = [
    ...new Set([...(score.unknown_reasons ?? []), ...(score.v2_unknown_reasons ?? [])]),
  ];
  const children: Node[] = [];
  if (reasons.length) {
    const list = document.createElement("ul");
    list.className = "notes-list";
    for (const reason of reasons) {
      list.append(textElement("li", "", reasonLabel(reason)));
    }
    children.push(list);
  }
  if (!score.score_available) {
    children.push(
      textElement("p", "state-message", "This value is diagnostic; no qualified score is available."),
    );
  }
  if (score.status === "SEPARATE_MODEL") {
    children.push(
      textElement("p", "state-message", "This company is scored with a separate model."),
    );
  }
  notes.replaceChildren(
    ...(children.length ? children : [textElement("p", "state-message", "No data gaps reported.")]),
  );
}

function renderProvenance(score: QualityScoreView | null): void {
  const provenance = byId("quality-provenance");
  if (!score) {
    provenance.textContent = "";
    return;
  }
  provenance.textContent = [
    score.rule_version,
    `Snapshot ${score.snapshot_id}`,
    `Calculated ${formatDate(score.calculated_at)}`,
  ].join("  ·  ");
}

export function renderCompanyScore(
  score: QualityScoreView | null,
  ticker = "",
  error?: string,
): void {
  renderHeader(score, ticker, error);
  renderSummary(score, error);
  renderDimensions(score);
  renderStrength(score);
  renderNotes(score);
  renderProvenance(score);
}

export async function mountCompanyPage(): Promise<void> {
  markCurrentNav(window.location.pathname);
  const ticker = readTicker(new URL(window.location.href));
  if (!ticker) {
    renderCompanyScore(null, "", "Add a valid ticker query parameter.");
    renderAnalystOpinions(null);
    return;
  }

  const [score, opinions] = await Promise.allSettled([
    loadQualityScore(ticker),
    loadAnalystOpinions(ticker),
  ]);
  if (score.status === "fulfilled") {
    renderCompanyScore(score.value, ticker);
  } else {
    renderCompanyScore(null, ticker, "Quality score request failed.");
  }
  renderAnalystOpinions(opinions.status === "fulfilled" ? opinions.value : null);
}

if (document.querySelector("[data-company-app]")) {
  void mountCompanyPage();
}
