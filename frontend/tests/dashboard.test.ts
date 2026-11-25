import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  buildIndicatorTiles,
  buildMarketSections,
  buildMovers,
  formatDayChange,
  formatMarketCap,
  formatMarketValue,
  formatPct,
  formatScore,
  mountOverview,
  polarity,
  sparkPoints,
} from "../src/pages/dashboard";
import type {
  MarketView,
  OverviewView,
} from "../src/api/types";

const overview: OverviewView = {
  as_of: "2026-11-23",
  total_companies: 234,
  tiers: { "1": 40, "2": 80, "3": 114 },
  total_market_cap: 12_345_000_000_000,
  avg_quality_score: 72.5,
  gainers: [
    { ticker: "NVDA", name: "NVIDIA", price: 130.5, change_pct: 2.3 },
    { ticker: "AMD", name: "AMD", price: 22.1, change_pct: 1.1 },
  ],
  losers: [
    { ticker: "MU", name: "Micron", price: 88.2, change_pct: -3.4 },
  ],
};

const market: MarketView = {
  as_of: "2026-11-23",
  categories: [
    { id: "us", label: "US Broad Market" },
    { id: "macro", label: "Rates, Volatility & Dollar" },
    { id: "crypto", label: "Crypto" },
  ],
  indices: [
    { symbol: "^GSPC", label: "S&P 500", category: "us", unit: "index", close: 6123.4, change: 31.2, change_pct: 0.5, change_1w: -1.2, change_1m: 4.8, high_1m: 6210, low_1m: 5890, spark: [6100, 6120, 6123.4] },
    { symbol: "^VIX", label: "VIX", category: "macro", unit: "index", close: 14.2, change: -0.16, change_pct: -1.1, change_1w: null, change_1m: -8.0, spark: [16, 15, 14.2] },
    { symbol: "^TNX", label: "10Y Treasury Yield", category: "macro", unit: "pct", close: 4.052, change: 0.048, change_pct: 1.2, high_1m: 4.2, low_1m: 3.9, spark: [3.9, 4.0, 4.052] },
    { symbol: "BTC-USD", label: "Bitcoin", category: "crypto", unit: "usd", close: 95000, change: 437, change_pct: 0.5, high_1m: 100000, low_1m: 88000, spark: [90000, 95000] },
  ],
};

describe("overview formatters", () => {
  it("formats market cap in human units", () => {
    expect(formatMarketCap(null)).toBe("—");
    expect(formatMarketCap(12_345_000_000_000)).toBe("12.3T");
    expect(formatMarketCap(845_000_000_000)).toBe("845.0B");
    expect(formatMarketCap(56_000_000)).toBe("56.0M");
  });

  it("formats the quality score to one decimal", () => {
    expect(formatScore(null)).toBe("—");
    expect(formatScore(72.5)).toBe("72.5");
    expect(formatScore(68)).toBe("68.0");
  });

  it("formats signed percentage", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(2.34)).toBe("+2.3%");
    expect(formatPct(-1.5)).toBe("-1.5%");
    expect(formatPct(0)).toBe("0.0%");
  });

  it("derives up/down/flat polarity", () => {
    expect(polarity(null)).toBe("flat");
    expect(polarity(0.1)).toBe("up");
    expect(polarity(-0.1)).toBe("down");
    expect(polarity(0)).toBe("flat");
  });
});

describe("sparkPoints", () => {
  it("maps values onto a horizontal polyline", () => {
    expect(sparkPoints([1, 2, 3], 100, 40)).toBe("0,40 50,20 100,0");
  });

  it("centers a flat series", () => {
    expect(sparkPoints([5, 5, 5], 100, 40)).toBe("0,20 50,20 100,20");
  });

  it("returns empty for a single point", () => {
    expect(sparkPoints([1], 100, 40)).toBe("");
  });
});

describe("buildIndicatorTiles", () => {
  it("renders one tile per metric with formatted values", () => {
    const dl = buildIndicatorTiles(overview);
    const tiles = [...dl.querySelectorAll(".indicator-tile")];
    expect(tiles.length).toBe(6);
    const values = tiles.map((t) => t.querySelector("dd")?.textContent);
    expect(values).toContain("234");
    expect(values).toContain("12.3T");
    expect(values).toContain("72.5");
  });
});

describe("buildMovers", () => {
  it("links each mover to the company detail page", () => {
    const wrap = buildMovers(overview);
    const rows = [...wrap.querySelectorAll<HTMLAnchorElement>(".mover-row")];
    expect(rows.length).toBe(3);
    expect(rows[0].getAttribute("href")).toBe("company.html?ticker=NVDA");
    expect(wrap.querySelector(".mover-col.up .m-change")?.className).toContain("up");
  });
});

describe("market value formatting", () => {
  it("formats index, yield, and USD values by unit", () => {
    expect(formatMarketValue(null, "index")).toBe("—");
    expect(formatMarketValue(6123.4, "index")).toBe("6,123.4");
    expect(formatMarketValue(4.052, "pct")).toBe("4.05%");
    expect(formatMarketValue(4123.45, "usd")).toBe("$4,123");
    expect(formatMarketValue(5.1234, "usd")).toBe("$5.12");
    expect(formatMarketValue(95000, "usd")).toBe("$95,000");
  });

  it("renders day change as absolute plus percent, and percent-only for yields", () => {
    expect(formatDayChange(market.indices[0])).toBe("+31.2 (+0.5%)");
    expect(formatDayChange(market.indices[1])).toBe("-0.16 (-1.1%)");
    expect(formatDayChange(market.indices[2])).toBe("+0.05");
    expect(formatDayChange(market.indices[3])).toBe("+$437 (+0.5%)");
  });

  it("falls back to the percent when an older row has no absolute change", () => {
    const legacy = { ...market.indices[0], change: undefined };
    expect(formatDayChange(legacy)).toBe("+0.5%");
    expect(formatDayChange({ ...legacy, change_pct: null })).toBe("—");
  });
});

describe("buildMarketSections", () => {
  it("groups cards under one section per category in server order", () => {
    const wrap = buildMarketSections(market);
    const sections = [...wrap.querySelectorAll<HTMLElement>(".market-section")];
    expect(sections.map((s) => s.querySelector("h3")?.textContent)).toEqual([
      "US Broad Market",
      "Rates, Volatility & Dollar",
      "Crypto",
    ]);
    expect(sections.map((s) => s.querySelectorAll(".market-card").length)).toEqual([1, 2, 1]);
    expect(wrap.querySelectorAll(".market-card polyline").length).toBe(4);
    expect(wrap.textContent).toContain("S&P 500");
    expect(wrap.textContent).toContain("1W -1.2%");
    expect(wrap.textContent).toContain("1M +4.8%");
    // null 1W renders an em dash rather than a number.
    expect(wrap.textContent).toContain("1W —");
  });

  it("shows the symbol, unit-aware value, and 1M range per card", () => {
    const wrap = buildMarketSections(market);
    const cards = [...wrap.querySelectorAll<HTMLElement>(".market-card")];
    expect(cards[0].querySelector(".mc-symbol")?.textContent).toBe("^GSPC");
    expect(cards[0].querySelector(".mc-value")?.textContent).toBe("6,123.4");
    expect(cards[0].querySelector(".mc-change")?.textContent).toBe("+31.2 (+0.5%)");
    expect(cards[0].getAttribute("title")).toContain("1M range 5,890 – 6,210");
    expect(cards[2].querySelector(".mc-value")?.textContent).toBe("4.05%");
    expect(cards[3].querySelector(".mc-value")?.textContent).toBe("$95,000");
  });
});

describe("mountOverview", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <main data-overview-app>
        <div id="overview-indicators" role="status"></div>
        <div id="overview-movers" role="status"></div>
        <div id="overview-market" role="status"></div>
        <p id="overview-as-of"></p>
      </main>`;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("populates indicators, movers, and market from the endpoints", async () => {
    const byPath = (body: unknown) => ({
      ok: true,
      status: 200,
      json: async () => body,
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/overview")) return byPath(overview);
      if (url.includes("/api/v1/market")) return byPath(market);
      throw new Error(`unexpected ${url}`);
    }));

    await mountOverview();

    expect(document.querySelector("#overview-indicators .indicator-tile")).toBeTruthy();
    expect(document.querySelectorAll("#overview-market .market-card").length).toBe(4);
    expect(document.querySelector("#overview-as-of")?.textContent).toContain("2026-11-23");
  });

  it("surfaces an error state on failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("network down");
    }));

    await mountOverview();

    const marketRegion = document.querySelector("#overview-market");
    expect(marketRegion?.textContent).toMatch(/unavailable/i);
    expect(marketRegion?.getAttribute("data-state")).toBe("error");
  });
});
