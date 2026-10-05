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
  it("round-trips filters, sort, and paging through the URL", () => {
    const state = readDirectoryState(
      new URLSearchParams(
        "query=nvda&layer=silicon&segment=Compute&status=parsed&sort=market_cap_desc&page=2&pageSize=50",
      ),
    );

    expect(state).toEqual({
      query: "nvda",
      layer: "silicon",
      segment: "Compute",
      status: "parsed",
      sort: "market_cap_desc",
      page: 2,
      pageSize: 50,
    });
    expect(writeDirectoryState(state).toString()).toBe(
      "query=nvda&layer=silicon&segment=Compute&status=parsed&sort=market_cap_desc&page=2&pageSize=50",
    );
  });

  it("normalizes invalid sort values to catalog order", () => {
    expect(readDirectoryState(new URLSearchParams("sort=change_pct")).sort).toBe("");
    expect(readDirectoryState(new URLSearchParams("sort=market_cap_asc")).sort).toBe(
      "market_cap_asc",
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

  it("renders the latest price and signed daily change in the price cell", () => {
    const up = { ...catalogOnlyCompany, ticker: "NVDA", price: 233.95, change_pct: 1.34 };
    const down = { ...catalogOnlyCompany, ticker: "TSLA", price: 288.4, change_pct: -2.1 };
    renderCompanies([up, down]);

    const cells = document.querySelectorAll(".price-cell");
    expect(cells.length).toBe(2);

    const value = document.querySelector(".price-value") as HTMLElement;
    expect(value.textContent).toBe("$233.95");
    const upChange = document.querySelector(".price-change.up") as HTMLElement;
    expect(upChange.textContent).toBe("+1.34%");

    const downChange = document.querySelector(".price-change.down") as HTMLElement;
    expect(downChange.textContent).toBe("-2.10%");
  });

  it("shows a muted placeholder when no price is available", () => {
    renderCompanies([catalogOnlyCompany]);

    const placeholder = document.querySelector(".price-na") as HTMLElement;
    expect(placeholder.textContent).toBe("—");
    expect(document.querySelector(".price-value")).toBeNull();
  });

  it("renders market cap in compact units next to the price", () => {
    const trillion = { ...catalogOnlyCompany, ticker: "NVDA", market_cap: 5_649_190_576_309 };
    const billion = { ...catalogOnlyCompany, ticker: "VRT", market_cap: 97_086_314_647 };
    const million = { ...catalogOnlyCompany, ticker: "RGTI", market_cap: 985_200_000 };
    renderCompanies([trillion, billion, million, catalogOnlyCompany]);

    const cells = document.querySelectorAll<HTMLTableCellElement>(".cap-cell");
    expect(cells.length).toBe(4);

    const values = Array.from(document.querySelectorAll(".cap-value")).map(
      (element) => element.textContent,
    );
    expect(values).toEqual(["$5.65T", "$97.09B", "$985.2M"]);

    // Column order follows the header: Company, layer, date, coverage, filings,
    // price, market cap, action.
    expect(cells[0].cellIndex).toBe(6);

    const missing = document.querySelector(".cap-na") as HTMLElement;
    expect(missing.textContent).toBe("—");
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
