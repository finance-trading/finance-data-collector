import { beforeEach, describe, expect, it } from "vitest";

import {
  companyStatusLabel,
  createCompanyState,
  disclosureBody,
  initializeFullTextModal,
  readTicker,
} from "../src/pages/company";
import { markCurrentNav } from "../src/components/site-shell";
describe("company research state", () => {
  it("normalizes the ticker from the query string", () => {
    expect(readTicker(new URL("http://test/company.html?ticker=nvda"))).toBe("NVDA");
    expect(readTicker(new URL("http://test/company.html?ticker=%3Cscript%3E"))).toBeNull();
  });

  it("does not let stale evidence replace a newer filing", () => {
    const state = createCompanyState();
    state.selectFiling("old-accession");
    const stale = state.beginEvidence("old-accession");
    state.selectFiling("new-accession");

    expect(state.acceptEvidence(stale)).toBe(false);
    expect(state.acceptEvidence(state.beginEvidence("new-accession"))).toBe(true);
  });

  it("maps HTTP failures to explicit labels", () => {
    expect(companyStatusLabel(404)).toBe("Not found");
    expect(companyStatusLabel(409)).toBe("Unavailable");
    expect(companyStatusLabel(422)).toBe("Parse failed");
  });
});

const LONG_PROSE = "Net revenue was $30 billion for the year, an increase of $6 billion or 25 percent from the prior year.\n\n".repeat(30);

describe("disclosure full text", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="host"></div>
      <div id="full-text" class="full-text-modal" role="dialog" aria-hidden="true">
        <div class="full-text-header">
          <h3 id="full-text-title">Full text</h3>
          <button id="full-text-close" type="button">Close</button>
        </div>
        <article id="full-text-body"></article>
      </div>
    `;
    initializeFullTextModal();
  });

  it("keeps short prose inline without a full-text trigger", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody("Net revenue was $30 billion.", "Management discussion"));

    const copy = host.querySelector<HTMLElement>(".disclosure-copy")!;
    expect(copy.classList.contains("is-truncated")).toBe(false);
    expect(host.querySelector(".expand-text")).toBeNull();
    expect(copy.textContent).toBe("Net revenue was $30 billion.");
  });

  it("truncates long prose but keeps the full text reachable in the modal", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody(LONG_PROSE, "Management discussion"));

    const copy = host.querySelector<HTMLElement>(".disclosure-copy")!;
    expect(copy.classList.contains("is-truncated")).toBe(true);
    // The display is a short word-boundary cut; the parsed text is stashed
    // off-DOM so the trigger's own label cannot pollute it.
    expect(copy.textContent.length).toBeLessThan(LONG_PROSE.length / 2);
    expect(copy.getAttribute("data-full-text")).toBe(LONG_PROSE);

    host.querySelector<HTMLElement>(".expand-text")!.dispatchEvent(new Event("click"));
    const modal = document.querySelector<HTMLElement>("#full-text")!;
    expect(modal.classList.contains("is-open")).toBe(true);
    expect(modal.getAttribute("aria-hidden")).toBe("false");
    expect(modal.querySelector<HTMLElement>("#full-text-body")!.textContent).toBe(LONG_PROSE);
  });

  it("cuts the excerpt at a word boundary, not mid-token", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody(`alpha ${"word ".repeat(200)}`, "Management discussion"));

    // textContent = "alpha word …" + button label; the prose part ends on a
    // space + ellipsis, so the last whole word before the cut is intact.
    const copy = host.querySelector<HTMLElement>(".disclosure-copy")!;
    const shown = copy.textContent.replace(copy.querySelector(".expand-text")!.textContent ?? "", "");
    // Ends on the ellipsis; the cut sat on a word boundary, so the prose
    // part is "alpha" plus a whole number of complete "word"s.
    expect(shown.endsWith("…")).toBe(true);
    expect(shown.slice(0, -1)).toMatch(/^alpha( word)*$/);
  });

  it("clears the modal on close and lets Escape and backdrop clicks close it", () => {
    const host = document.querySelector<HTMLElement>("#host")!;
    host.append(disclosureBody(LONG_PROSE, "Management discussion"));
    const modal = document.querySelector<HTMLElement>("#full-text")!;
    const trigger = () => host.querySelector<HTMLElement>(".expand-text")!;
    const open = () => trigger().dispatchEvent(new Event("click"));

    open();
    document.querySelector<HTMLElement>("#full-text-close")!.dispatchEvent(new Event("click"));
    expect(modal.classList.contains("is-open")).toBe(false);
    expect(modal.getAttribute("aria-hidden")).toBe("true");
    expect(modal.querySelector<HTMLElement>("#full-text-body")!.textContent).toBe("");

    open();
    document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));
    expect(modal.classList.contains("is-open")).toBe(false);

    open();
    modal.dispatchEvent(new Event("click"));
    expect(modal.classList.contains("is-open")).toBe(false);
  });
});

describe("site shell", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <nav>
        <a data-nav href="http://test/index.html">AI companies</a>
        <a data-nav href="http://test/graph.html">Company graph</a>
      </nav>
    `;
  });

  it("marks only the current navigation destination", () => {
    markCurrentNav("/graph.html");

    expect(document.querySelector("[href='http://test/graph.html']")?.getAttribute("aria-current"))
      .toBe("page");
    expect(document.querySelector("[href='http://test/index.html']")?.hasAttribute("aria-current"))
      .toBe(false);
  });
});

describe("quality score page state", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <article id="quality-score" aria-labelledby="quality-score-title">
        <div class="quality-header">
          <h2 id="quality-score-title">Quality score</h2>
          <p class="state-message" role="status">Loading quality score…</p>
        </div>
      </article>
    `;
  });

  const score = {
    ticker: "AAPL", cik: "0000320193", company_name: "Apple Inc.", sector: "Technology",
    rating_cutoff: "2026-09-30", calculated_at: "2026-10-05T00:00:00Z",
    snapshot_id: "seed", rule_version: "CQ_V2", semantic_policy: "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2",
    source_facts_sha256: "a".repeat(64), quality_score: "70.666667", score_available: true,
    status: "QUALIFIED", dimension_count: 5, peer_count: 12, period_ends: ["2021-09-25", "2026-09-30"],
    revenue_growth_dimension: "83.1", operating_margin_dimension: "23.2", cash_conversion_dimension: "22.5",
    capital_efficiency_dimension: "18.3", financial_strength_dimension: "76.4", unknown_reasons: [],
    v2_hard_status: "QUALIFIED", v2_unknown_reasons: [], v2_hard_gate_count: 5, v2_hard_gate_total: 5,
    v2_net_debt_ebitda: "0.1", v2_interest_coverage: "12.4", v2_cumulative_net_income: "300000000000",
    v2_cumulative_cfo: "400000000000", v2_positive_operating_income_years: 5, v2_positive_cfo_years: 5,
  };

  it("shows the score, dimensions, gates, and cutoff", async () => {
    const {renderQualityScore} = await import("../src/pages/company");
    renderQualityScore(score);
    const panel = document.querySelector<HTMLElement>("#quality-score")!;
    expect(panel.querySelector(".quality-score-value")?.textContent).toBe("70.67");
    expect(panel.textContent).toContain("Revenue growth");
    expect(panel.textContent).toContain("Financial strength");
    expect(panel.textContent).toContain("HARD_GATES_PASS");
    expect(panel.textContent).toContain("Cutoff 2026-09-30");
  });

  it("keeps diagnostic scores visibly non-certified", async () => {
    const {renderQualityScore} = await import("../src/pages/company");
    renderQualityScore({...score, score_available: false, quality_score: "53.977273", status: "NOT_QUALIFIED"});
    const panel = document.querySelector<HTMLElement>("#quality-score")!;
    expect(panel.querySelector(".quality-score-value")?.textContent).toBe("53.98");
    expect(panel.textContent).toContain("Diagnostic score only");
  });

  it("renders no-record and request-failure states", async () => {
    const {renderQualityScore} = await import("../src/pages/company");
    renderQualityScore(null);
    expect(document.querySelector("#quality-score")?.textContent).toContain("No score record");
    renderQualityScore(null, "Quality score request failed");
    expect(document.querySelector("#quality-score [role=alert]")?.textContent).toContain("request failed");
  });

  it("labels model statuses without treating them as zero", async () => {
    const {qualityScoreStateLabel} = await import("../src/pages/company");
    expect(qualityScoreStateLabel("QUALIFIED")).toBe("Qualified");
    expect(qualityScoreStateLabel("SEPARATE_MODEL")).toBe("Separate model");
    expect(qualityScoreStateLabel("UNKNOWN")).toBe("Unknown");
  });
});
