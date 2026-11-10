import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatRefreshTime,
  nextSort,
  observationBandCell,
  readDirectoryState,
  renderCompanies,
  sortKeyOf,
  syncSortHeaders,
  watchItemsCell,
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
      layers: ["silicon"],
      segment: "Compute",
      tier: "",
      status: "parsed",
      sort: "market_cap_desc",
      page: 2,
      pageSize: 50,
    });
    expect(writeDirectoryState(state).toString()).toBe(
      "query=nvda&layer=silicon&segment=Compute&status=parsed&sort=market_cap_desc&page=2&pageSize=50",
    );
  });

  it("round-trips multiple layers and removes duplicates", () => {
    const state = readDirectoryState(new URLSearchParams("layer=silicon&layer=power&layer=silicon"));
    expect(state.layers).toEqual(["silicon", "power"]);
    expect(writeDirectoryState(state).getAll("layer")).toEqual(["silicon", "power"]);
  });

  it("normalizes invalid sort values to catalog order", () => {
    expect(readDirectoryState(new URLSearchParams("sort=change_pct")).sort).toBe("");
    expect(readDirectoryState(new URLSearchParams("sort=market_cap_asc")).sort).toBe(
      "market_cap_asc",
    );
    expect(readDirectoryState(new URLSearchParams("sort=week_rise_pct_asc")).sort).toBe(
      "week_rise_pct_asc",
    );
    expect(readDirectoryState(new URLSearchParams("sort=rise_52w_pct_desc")).sort).toBe(
      "rise_52w_pct_desc",
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
            <button class="sort-button" data-sort="change_pct">Price<span class="sort-indicator"></span></button>
          </th>
          <th data-sort-column="market_cap" aria-sort="none">
            <button class="sort-button" data-sort="market_cap">Market cap<span class="sort-indicator"></span></button>
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
    vi.restoreAllMocks();
  });

  it("saves a manual tier with a reason, then resets to auto", async () => {
    const company = {
      ...catalogOnlyCompany, funnel_tier: 2, funnel_tier_name: "重要", funnel_tier_source: "自动",
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        tier: 1, tier_name: "核心", source: "人工", note: "关键客户", auto_tier: 2,
      }), {status: 200}))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        tier: 2, tier_name: "重要", source: "自动", note: "", auto_tier: 2,
      }), {status: 200}));
    renderCompanies([company]);
    const badge = () => document.querySelector<HTMLButtonElement>(".tier-cell button.tier-badge")!;
    badge().click();
    const form = document.querySelector<HTMLFormElement>(".tier-editor")!;
    const select = form.querySelector("select")!;
    const note = form.querySelector("input")!;
    expect(select.value).toBe("auto");
    select.value = "1";
    select.dispatchEvent(new Event("change"));
    note.value = "关键客户";
    form.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    await vi.waitFor(() => expect(badge().textContent).toBe("T1 核心"));
    expect(badge().dataset.source).toBe("人工");
    expect(fetchMock.mock.calls[0][1]?.headers).toEqual({"Content-Type": "application/json"});
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      ticker: "VRT", tier: 1, note: "关键客户",
    });
    badge().click();
    const resetForm = document.querySelector<HTMLFormElement>(".tier-editor")!;
    expect(resetForm.querySelector("select")?.value).toBe("1");
    const resetSelect = resetForm.querySelector("select")!;
    resetSelect.value = "auto";
    resetSelect.dispatchEvent(new Event("change"));
    resetForm.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    await vi.waitFor(() => expect(badge().textContent).toBe("T2 重要"));
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).tier).toBeNull();
  });

  it("keeps the tier editor open when saving fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("error", {status: 500}));
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderCompanies([{...catalogOnlyCompany, funnel_tier: 2, funnel_tier_name: "重要"}]);
    document.querySelector<HTMLButtonElement>(".tier-cell button")!.click();
    const form = document.querySelector<HTMLFormElement>(".tier-editor")!;
    const select = form.querySelector("select")!;
    select.value = "1";
    select.dispatchEvent(new Event("change"));
    form.querySelector("input")!.value = "原因";
    form.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    await vi.waitFor(() => expect(form.querySelector(".tier-error")?.textContent).toContain("保存失败"));
    expect(form.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(false);
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
    const unavailable = document.querySelector(".availability-missing") as HTMLElement;
    expect(unavailable.textContent).toBe("—");
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

  it("renders market cap in millions next to the price", () => {
    const trillion = { ...catalogOnlyCompany, ticker: "NVDA", market_cap: 5_649_190_576_309 };
    const billion = { ...catalogOnlyCompany, ticker: "VRT", market_cap: 97_086_314_647 };
    const million = { ...catalogOnlyCompany, ticker: "RGTI", market_cap: 985_200_000 };
    renderCompanies([trillion, billion, million, catalogOnlyCompany]);

    const cells = document.querySelectorAll<HTMLTableCellElement>(".cap-cell");
    expect(cells.length).toBe(4);

    const values = Array.from(document.querySelectorAll(".cap-value")).map(
      (element) => element.textContent,
    );
    expect(values).toEqual(["$5,649,191M", "$97,086M", "$985.2M"]);

    // Column order follows the header: Company, layer, tier, date, price,
    // 1W DD, 1W Rise, 52W DD, 52W Rise, P/E, EPS, Fwd P/E, Fwd EPS,
    // Intrinsic, Bear, Base, Bull, market cap, action.
    expect(cells[0].cellIndex).toBe(17);

    const missing = document.querySelector(".cap-na") as HTMLElement;
    expect(missing.textContent).toBe("—");
  });

  it("renders one-week and 52-week drawdown and rise as separate columns", () => {
    renderCompanies([
      {
        ...catalogOnlyCompany,
        ticker: "NVDA",
        week_change_pct: 3.42,
        week_rise_pct: 9.8,
        change_52w_pct: -18.07,
        rise_52w_pct: 41.0,
      },
      catalogOnlyCompany,
    ]);

    const text = (label: string): string | null =>
      document.querySelector(`td[data-label="${label}"]`)?.textContent ?? null;

    expect(text("1W DD")).toBe("▲ 3.42%");
    expect(text("1W Rise")).toBe("▲ 9.80%");
    expect(text("52W DD")).toBe("▼ 18.07%");
    expect(text("52W Rise")).toBe("▲ 41.00%");

    // The four columns sit between price and P/E.
    expect(
      (document.querySelector('td[data-label="1W DD"]') as HTMLTableCellElement).cellIndex,
    ).toBe(5);
    expect(
      (document.querySelector('td[data-label="52W Rise"]') as HTMLTableCellElement).cellIndex,
    ).toBe(8);

    // A stale cache without the new keys degrades to the muted placeholder.
    const missing = document.querySelectorAll('tr td[data-label="1W DD"]')[1];
    expect(missing.textContent).toBe("—");
  });

  it("renders intrinsic value and the three scenario prices", () => {
    renderCompanies([
      {
        ...catalogOnlyCompany,
        ticker: "NVDA",
        intrinsic_value: 307.84,
        scen_bear: 225.24,
        scen_base: 304.84,
        scen_bull: 396.46,
      },
      catalogOnlyCompany,
    ]);

    const text = (label: string, index = 0): string | null =>
      document.querySelectorAll(`tr td[data-label="${label}"]`)[index]?.textContent ?? null;

    expect(text("Intrinsic", 0)).toBe("307.84");
    expect(text("Bear", 0)).toBe("225.24");
    expect(text("Base", 0)).toBe("304.84");
    expect(text("Bull", 0)).toBe("396.46");

    // A company with no saved valuation degrades to the muted placeholder.
    expect(text("Intrinsic", 1)).toBe("—");
    expect(text("Bull", 1)).toBe("—");

    // The four columns sit after Fwd EPS and before market cap.
    expect(
      (document.querySelector('td[data-label="Intrinsic"]') as HTMLTableCellElement).cellIndex,
    ).toBe(13);
    expect(
      (document.querySelector('td[data-label="Bull"]') as HTMLTableCellElement).cellIndex,
    ).toBe(16);
  });

  it("edits and saves the four price intervals", async () => {
    const company = {...catalogOnlyCompany, watch_items: [], annotation_saved: false};
    const saved = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({annotation_saved: true}), {status: 200}),
    );
    const band = observationBandCell(company);
    band.querySelector<HTMLButtonElement>(".annotation-edit")!.click();
    const inputs = band.querySelectorAll<HTMLInputElement>(".range-edit-row input");
    inputs[0].value = "180";
    inputs[1].value = "200";
    const form = band.querySelector<HTMLFormElement>("form")!;
    form.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    await vi.waitFor(() => expect(band.textContent).toContain("$180.00–$200.00"));
    expect(JSON.parse(String(saved.mock.calls[0][1]?.body)).observation_range).toEqual({
      low: 180, high: 200,
    });
    expect(company.annotation_saved).toBe(true);
  });

  it("keeps price editor open and data unchanged on save failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("error", {status: 500}));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const company = {...catalogOnlyCompany, observation_range: {low: null, high: null}};
    const band = observationBandCell(company);
    band.querySelector<HTMLButtonElement>(".annotation-edit")!.click();
    const inputs = band.querySelectorAll<HTMLInputElement>(".range-edit-row input");
    inputs[0].value = "180";
    inputs[1].value = "200";
    band.querySelector("form")!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    await vi.waitFor(() => expect(band.querySelector(".annotation-error")?.textContent).toContain("保存失败"));
    expect(company.observation_range).toEqual({low: null, high: null});
    expect(band.querySelector("form")).not.toBeNull();
  });

  it("edits watch items, orders by priority, and persists deletions", async () => {
    const company = {
      ...catalogOnlyCompany,
      watch_items: [
        {priority: 2 as const, text: "Track revenue", code: "FIN", next_check_at: "2026-12-01", updated_at: "2026-11-01T08:00:00+00:00"},
        {priority: 1 as const, text: "Review margins"},
      ],
    };
    const saved = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({annotation_saved: true}), {status: 200}),
    );
    const watch = watchItemsCell(company);
    expect([...watch.querySelectorAll(".watch-priority")].map((node) => node.textContent)).toEqual(["P1", "P2"]);
    expect(watch.querySelector(".watch-code")!.textContent).toBe("FIN");
    expect([...watch.querySelectorAll(".watch-updated")].map((node) => node.textContent)).toEqual(["2026-11-01"]);
    watch.querySelector<HTMLButtonElement>(".annotation-edit")!.click();
    const removeButtons = watch.querySelectorAll<HTMLButtonElement>(".watch-edit-row button");
    removeButtons[1].click();
    watch.querySelector("form")!.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    await vi.waitFor(() => expect(watch.querySelectorAll(".watch-item").length).toBe(1));
    expect(JSON.parse(String(saved.mock.calls[0][1]?.body)).watch_items).toEqual([
      {priority: 2, text: "Track revenue", code: "FIN", next_check_at: "2026-12-01"},
    ]);
    expect(JSON.stringify(JSON.parse(String(saved.mock.calls[0][1]?.body)))).not.toContain("updated_at");
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
