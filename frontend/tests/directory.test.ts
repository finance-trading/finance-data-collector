import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatRefreshTime,
  nextSort,
  readDirectoryState,
  renderCompanies,
  sortKeyOf,
  syncSortHeaders,
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

describe("quote refresh time", () => {
  it("formats the cache stamp as a readable UTC timestamp", () => {
    expect(formatRefreshTime("2026-10-08T13:00:00+00:00")).toBe(
      "Oct 8, 2026, 1:00 PM",
    );
  });

  it("returns an empty string when there is no refresh stamp", () => {
    expect(formatRefreshTime(null)).toBe("");
  });
});

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

describe("directory sorting", () => {
  it("starts a freshly activated column descending, then flips it", () => {
    expect(nextSort("", "market_cap")).toBe("market_cap_desc");
    expect(nextSort("market_cap_desc", "market_cap")).toBe("market_cap_asc");
    expect(nextSort("market_cap_asc", "market_cap")).toBe("market_cap_desc");
  });

  it("restarts descending when a different column is activated", () => {
    expect(nextSort("market_cap_asc", "change_pct")).toBe("change_pct_desc");
    expect(nextSort("change_pct_desc", "market_cap")).toBe("market_cap_desc");
  });

  it("maps a sort state onto its key, and reports catalog order as none", () => {
    expect(sortKeyOf("market_cap_asc")).toBe("market_cap");
    expect(sortKeyOf("change_pct_desc")).toBe("change_pct");
    expect(sortKeyOf("")).toBeNull();
  });

  it("marks only the active column and points its arrow the right way", () => {
    document.body.innerHTML = `
      <table>
        <thead><tr>
          <th data-sort-column="change_pct" aria-sort="none">
            <button class="sort-button">Price<span class="sort-indicator"></span></button>
          </th>
          <th data-sort-column="market_cap" aria-sort="none">
            <button class="sort-button">Market cap<span class="sort-indicator"></span></button>
          </th>
        </tr></thead>
      </table>`;

    syncSortHeaders("market_cap_asc");

    const headers = document.querySelectorAll<HTMLTableCellElement>("th[data-sort-column]");
    expect(headers[0].getAttribute("aria-sort")).toBe("none");
    expect(headers[1].getAttribute("aria-sort")).toBe("ascending");
    expect(headers[1].querySelector(".sort-indicator")?.textContent).toBe("▲");
    expect(headers[0].querySelector(".sort-indicator")?.textContent).toBe("");

    syncSortHeaders("market_cap_desc");
    expect(headers[1].getAttribute("aria-sort")).toBe("descending");
    expect(headers[1].querySelector(".sort-indicator")?.textContent).toBe("▼");
  });
});

describe("directory rendering", () => {
  beforeEach(() => {
    document.body.innerHTML = '<table><tbody id="company-directory-body"></tbody></table>';
  });

  it("links every company to its stockanalysis quote page", () => {
    renderCompanies([catalogOnlyCompany, { ...catalogOnlyCompany, ticker: "ASML" }]);

    const links = [...document.querySelectorAll<HTMLAnchorElement>(".company-identity")];
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://stockanalysis.com/stocks/vrt/",
      "https://stockanalysis.com/stocks/asml/",
    ]);
    expect(links[0].getAttribute("target")).toBe("_blank");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("keeps the filing workspace link in the action column", () => {
    renderCompanies([catalogOnlyCompany]);

    expect(document.querySelector(".company-identity[href*='company.html']")).toBeNull();
    expect(document.body.textContent).toContain("Not ingested");
  });

  it("links companies with research data to the company workspace", () => {
    renderCompanies([{...catalogOnlyCompany, research_available: true, ticker: "NVDA"}]);

    expect(document.querySelector(".action-cell a")?.getAttribute("href")).toBe(
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
    expect(upChange.textContent).toBe("▲ 1.34%");

    const downChange = document.querySelector(".price-change.down") as HTMLElement;
    expect(downChange.textContent).toBe("▼ 2.10%");
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
    // price, 1W, 52W, market cap, action.
    expect(cells[0].cellIndex).toBe(8);

    const missing = document.querySelector(".cap-na") as HTMLElement;
    expect(missing.textContent).toBe("—");
  });

  it("renders one-week and 52-week changes in their own signed cells", () => {
    renderCompanies([
      {
        ...catalogOnlyCompany,
        ticker: "NVDA",
        week_change_pct: 3.42,
        change_52w_pct: -18.07,
      },
      catalogOnlyCompany,
    ]);

    const week = document.querySelectorAll<HTMLTableCellElement>(".week-cell");
    const year = document.querySelectorAll<HTMLTableCellElement>(".year-cell");
    expect(week.length).toBe(2);
    expect(year.length).toBe(2);

    expect(week[0].querySelector(".price-change.up")?.textContent).toBe("▲ 3.42%");
    expect(year[0].querySelector(".price-change.down")?.textContent).toBe("▼ 18.07%");
    expect(week[0].cellIndex).toBe(6);
    expect(year[0].cellIndex).toBe(7);

    // A stale cache without the new keys degrades to the muted placeholder.
    expect(week[1].querySelector(".price-na")?.textContent).toBe("—");
    expect(year[1].querySelector(".price-na")?.textContent).toBe("—");
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
