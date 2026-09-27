import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  readDirectoryState,
  renderCompanies,
  writeDirectoryState,
} from "../src/pages/directory";
import { renderPagination } from "../src/components/pagination";
import type { CompanyDirectoryItem } from "../src/api/types";

const catalogOnlyCompany: CompanyDirectoryItem = {
  ticker: "VRT",
  name: "Vertiv",
  sector: "Industrials",
  industry: "Electrical Equipment",
  layer: "power",
  layer_name: "Energy & Power",
  segment: "Power Infrastructure",
  description: "Power infrastructure",
  also_in: [],
  cik: null,
  latest_filing_date: null,
  latest_filing_status: null,
  ingestion_status: "not_ingested",
  filing_count: 0,
  research_available: false,
};

describe("directory URL state", () => {
  it("round-trips filters and paging through the URL", () => {
    const state = readDirectoryState(
      new URLSearchParams(
        "query=nvda&layer=silicon&segment=Compute&status=parsed&page=2&pageSize=50",
      ),
    );

    expect(state).toEqual({
      query: "nvda",
      layer: "silicon",
      segment: "Compute",
      status: "parsed",
      page: 2,
      pageSize: 50,
    });
    expect(writeDirectoryState(state).toString()).toBe(
      "query=nvda&layer=silicon&segment=Compute&status=parsed&page=2&pageSize=50",
    );
  });

  it("normalizes invalid page values to supported defaults", () => {
    expect(
      readDirectoryState(new URLSearchParams("page=0&pageSize=30&status=unknown")),
    ).toMatchObject({page: 1, pageSize: 25, status: ""});
  });
});

describe("directory rendering", () => {
  beforeEach(() => {
    document.body.innerHTML = '<table><tbody id="company-directory-body"></tbody></table>';
  });

  it("does not link catalog-only companies to missing research", () => {
    renderCompanies([catalogOnlyCompany]);

    expect(document.querySelector("a[href*='company.html']")).toBeNull();
    expect(document.body.textContent).toContain("Not ingested");
    expect(document.body.textContent).toContain("VRT");
  });

  it("links companies with research data to the company workspace", () => {
    renderCompanies([{...catalogOnlyCompany, research_available: true, ticker: "NVDA"}]);

    expect(document.querySelector("a")?.getAttribute("href")).toBe(
      "company.html?ticker=NVDA",
    );
  });
});

describe("pagination", () => {
  it("disables boundary actions and reports the visible result range", () => {
    document.body.innerHTML = '<nav id="directory-pagination"></nav>';
    const onPage = vi.fn();

    renderPagination(
      document.querySelector("#directory-pagination") as HTMLElement,
      {page: 1, pageSize: 25, total: 211},
      onPage,
    );

    const buttons = document.querySelectorAll("button");
    expect((buttons[0] as HTMLButtonElement).disabled).toBe(true);
    expect(document.body.textContent).toContain("1–25 of 211");
    buttons[buttons.length - 1].click();
    expect(onPage).toHaveBeenCalledWith(2);
  });
});
