import { beforeEach, describe, expect, it } from "vitest";

import type { QualityScoreView } from "../src/api/types";
import {
  qualityScoreStateLabel,
  readTicker,
  renderCompanyScore,
} from "../src/pages/company";

function mountShell() {
  document.body.innerHTML = `
    <header class="company-header">
      <h1 id="company-name">Loading company</h1>
      <p id="company-identity"></p>
      <span id="company-status" class="status status-loading">Loading</span>
    </header>
    <main data-company-app>
      <section id="quality-score">
        <h2 id="quality-score-title">Quality score</h2>
        <div id="quality-score-body" role="status">Loading quality score…</div>
      </section>
      <div id="quality-dimensions"></div>
      <div id="financial-strength"></div>
      <div id="quality-notes"></div>
      <p id="quality-provenance"></p>
    </main>
  `;
}

const SCORE: QualityScoreView = {
  ticker: "MSFT",
  cik: "0000000000",
  company_name: "Microsoft Fixture Corporation",
  sector: "Technology",
  rating_cutoff: "2026-09-30",
  calculated_at: "2026-10-05T00:00:00Z",
  snapshot_id: "acceptance-cq-v2",
  rule_version: "CQ_V2",
  semantic_policy: "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2",
  source_facts_sha256: "a".repeat(64),
  quality_score: "42.50",
  score_available: true,
  status: "QUALIFIED",
  dimension_count: 5,
  peer_count: 20,
  period_ends: ["2023-06-30", "2024-06-30"],
  revenue_growth_dimension: "10.25",
  operating_margin_dimension: "8.10",
  cash_conversion_dimension: "9.75",
  capital_efficiency_dimension: "11.50",
  financial_strength_dimension: "3.50",
  unknown_reasons: ["missing_cash_flow"],
  v2_hard_status: "QUALIFIED",
  v2_unknown_reasons: [],
  v2_hard_gate_count: 5,
  v2_hard_gate_total: 5,
  v2_net_debt_ebitda: "0.80",
  v2_interest_coverage: "12.50",
  v2_cumulative_net_income: "120.25",
  v2_cumulative_cfo: "150.75",
  v2_positive_operating_income_years: 4,
  v2_positive_cfo_years: 5,
};

describe("company quality page", () => {
  beforeEach(mountShell);

  it("normalizes the ticker from the query string", () => {
    expect(readTicker(new URL("http://test/company.html?ticker=nvda"))).toBe("NVDA");
    expect(readTicker(new URL("http://test/company.html?ticker=%3Cscript%3E"))).toBeNull();
  });

  it("maps quality statuses to readable labels", () => {
    expect(qualityScoreStateLabel("QUALIFIED")).toBe("Qualified");
    expect(qualityScoreStateLabel("NOT_QUALIFIED")).toBe("Not qualified");
    expect(qualityScoreStateLabel("SEPARATE_MODEL")).toBe("Separate model");
    expect(qualityScoreStateLabel("UNKNOWN")).toBe("Unknown");
  });

  it("renders the company overview from the latest score", () => {
    renderCompanyScore(SCORE);

    expect(document.querySelector("#company-name")?.textContent).toBe(
      "Microsoft Fixture Corporation",
    );
    expect(document.querySelector("#company-identity")?.textContent).toContain("MSFT");
    expect(document.querySelector("#company-identity")?.textContent).toContain("Technology");
    expect(document.querySelector("#company-status")?.textContent).toBe("Qualified");
    expect(document.title).toBe("Microsoft Fixture Corporation quality | Finance Data Collector");
  });

  it("renders the headline score and all five dimensions", () => {
    renderCompanyScore(SCORE);

    const summary = document.querySelector("#quality-score-body")?.textContent ?? "";
    expect(summary).toContain("42.50");
    expect(summary).toContain("Qualified");
    expect(summary).toContain("Calculated Oct 5, 2026");

    const dimensions = document.querySelector("#quality-dimensions")?.textContent ?? "";
    expect(dimensions).toContain("Revenue growth");
    expect(dimensions).toContain("10.25");
    expect(dimensions).toContain("Operating margin");
    expect(dimensions).toContain("8.10");
    expect(dimensions).toContain("Cash conversion");
    expect(dimensions).toContain("9.75");
    expect(dimensions).toContain("Capital efficiency");
    expect(dimensions).toContain("11.50");
    expect(dimensions).toContain("Financial strength");
    expect(dimensions).toContain("3.50");
  });

  it("renders the financial-strength gate and diagnostic metrics", () => {
    renderCompanyScore(SCORE);

    const strength = document.querySelector("#financial-strength")?.textContent ?? "";
    expect(strength).toContain("Hard gates");
    expect(strength).toContain("5 / 5");
    expect(strength).toContain("Net debt / EBITDA");
    expect(strength).toContain("0.80");
    expect(strength).toContain("Interest coverage");
    expect(strength).toContain("12.50");
    expect(strength).toContain("Cumulative net income");
    expect(strength).toContain("120.25");
    expect(strength).toContain("Cumulative operating cash flow");
    expect(strength).toContain("150.75");
    expect(strength).toContain("Positive operating income years");
    expect(strength).toContain("4");
    expect(strength).toContain("Positive cash flow years");
    expect(strength).toContain("5");
  });

  it("renders score notes and provenance", () => {
    renderCompanyScore(SCORE);

    expect(document.querySelector("#quality-notes")?.textContent).toContain("Missing cash flow");
    expect(document.querySelector("#quality-provenance")?.textContent).toContain("CQ_V2");
    expect(document.querySelector("#quality-provenance")?.textContent).toContain(
      "acceptance-cq-v2",
    );
  });

  it("does not repeat the same unknown reason across both reason lists", () => {
    renderCompanyScore({
      ...SCORE,
      unknown_reasons: ["missing_cash_flow"],
      v2_unknown_reasons: ["missing_cash_flow"],
    });

    const notes = document.querySelector("#quality-notes")?.textContent ?? "";
    expect(notes.match(/Missing cash flow/g)).toHaveLength(1);
  });

  it("shows an explicit unavailable state when no score record exists", () => {
    renderCompanyScore(null, "MSFT");

    expect(document.querySelector("#company-name")?.textContent).toBe("MSFT");
    expect(document.querySelector("#company-status")?.textContent).toBe("Unavailable");
    expect(document.querySelector("#quality-score-body")?.textContent).toContain(
      "No score record is available for this company.",
    );
    expect(document.querySelector("#quality-score-body")?.getAttribute("role")).toBe("status");
  });

  it("shows a request failure as an alert", () => {
    renderCompanyScore(null, "MSFT", "Quality score request failed.");

    expect(document.querySelector("#company-status")?.textContent).toBe("Unavailable");
    expect(document.querySelector("#quality-score-body")?.textContent).toContain(
      "Quality score request failed.",
    );
    expect(document.querySelector("#quality-score-body")?.getAttribute("role")).toBe("alert");
  });
});
