import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  buildIndicatorTiles,
  buildMarketCards,
  buildMovers,
  buildNewsList,
  formatMarketCap,
  formatPct,
  formatScore,
  mountOverview,
  polarity,
  relativeTime,
  sparkPoints,
} from "../src/pages/dashboard";
import type {
  MarketView,
  NewsItemView,
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
  indices: [
    { symbol: "^GSPC", label: "S&P 500", close: 6123.4, change_pct: 0.5, spark: [6100, 6120, 6123.4] },
    { symbol: "^VIX", label: "VIX", close: 14.2, change_pct: -1.1, spark: [16, 15, 14.2] },
  ],
};

const news: NewsItemView[] = [
  { id: "n1", title: "Markets rally", url: "https://example.com/a", source: "CNBC", published_at: "2026-11-23T09:00:00Z" },
];

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

  it("renders compact relative time", () => {
    const now = Date.parse("2026-11-23T12:00:00Z");
    expect(relativeTime(new Date(now - 30_000).toISOString(), now)).toBe("just now");
    expect(relativeTime(new Date(now - 5 * 60_000).toISOString(), now)).toBe("5m");
    expect(relativeTime(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe("3h");
    expect(relativeTime(new Date(now - 2 * 86_400_000).toISOString(), now)).toBe("2d");
    expect(relativeTime("2026-01-05T00:00:00Z", now)).toBe("Jan 5");
    expect(relativeTime(null, now)).toBe("");
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

describe("buildMarketCards", () => {
  it("renders a card with a sparkline per index", () => {
    const wrap = buildMarketCards(market);
    expect(wrap.querySelectorAll(".market-card").length).toBe(2);
    expect(wrap.querySelectorAll(".market-card polyline").length).toBe(2);
    expect(wrap.textContent).toContain("S&P 500");
  });
});

describe("buildNewsList", () => {
  it("renders each item with source, time, and linked title", () => {
    const list = buildNewsList(news);
    const items = [...list.querySelectorAll(".news-item")];
    expect(items.length).toBe(1);
    const link = items[0].querySelector<HTMLAnchorElement>("a.ni-title")!;
    expect(link.href).toBe("https://example.com/a");
    expect(items[0].querySelector(".ni-source")?.textContent).toBe("CNBC");
  });
});

describe("mountOverview", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <main data-overview-app>
        <div id="overview-indicators" role="status"></div>
        <div id="overview-movers" role="status"></div>
        <div id="overview-market" role="status"></div>
        <ol id="overview-news" role="status"></ol>
        <button id="news-refresh" type="button" hidden></button>
        <p id="overview-as-of"></p>
      </main>`;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("populates every section from the three endpoints", async () => {
    const byPath = (path: string, body: unknown) => ({
      ok: true,
      status: 200,
      json: async () => body,
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/overview")) return byPath(url, overview);
      if (url.includes("/api/v1/market")) return byPath(url, market);
      if (url.includes("/api/v1/news")) return byPath(url, { items: news, as_of: "2026-11-23T09:00:00Z" });
      throw new Error(`unexpected ${url}`);
    }));

    await mountOverview();

    expect(document.querySelector("#overview-indicators .indicator-tile")).toBeTruthy();
    expect(document.querySelectorAll("#overview-market .market-card").length).toBe(2);
    expect(document.querySelectorAll("#overview-news .news-item").length).toBe(1);
    expect(document.querySelector<HTMLButtonElement>("#news-refresh")?.hidden).toBe(false);
  });

  it("surfaces an error state and hides the refresh button on failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new Error("network down");
    }));

    await mountOverview();

    const news = document.querySelector("#overview-news");
    expect(news?.textContent).toMatch(/failed|error|unavailable/i);
    expect(document.querySelector<HTMLButtonElement>("#news-refresh")?.hidden).toBe(true);
  });
});
