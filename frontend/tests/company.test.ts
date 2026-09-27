import { beforeEach, describe, expect, it } from "vitest";

import {
  companyStatusLabel,
  createCompanyState,
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

describe("site shell", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <nav>
        <a data-nav href="http://test/index.html">Research</a>
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
