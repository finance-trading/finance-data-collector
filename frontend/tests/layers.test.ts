import { beforeEach, describe, expect, it } from "vitest";

import {
  changeDirection,
  compareByMarketCap,
  createCollapseState,
  fitText,
  flattenLayers,
  formatChangePct,
  formatCompactUSD,
  formatPrice,
  mountLayers,
} from "../src/pages/layers";
import type { LayersPayload } from "../src/api/types";
import type { FlatCompany } from "../src/pages/layers";

const fixture: LayersPayload = {
  generated_at: "test",
  stats: {companies: 1, layers: 1, segments: 1, cross_layer: 0},
  root: {
    id: "ai",
    name: "AI stack",
    count: 1,
    children: [
      {
        id: "silicon",
        name: "Silicon",
        name_en: "Silicon",
        count: 1,
        summary: "Compute",
        children: [
          {
            id: "silicon/compute",
            name: "Compute",
            count: 1,
            children: [
              {
                id: "NVDA",
                type: "company",
                ticker: "NVDA",
                name: "NVIDIA",
                cik: 1045810,
                sector: "Technology",
                industry: "Semiconductors",
                layer: "silicon",
                segment: "Compute",
                description: "Accelerated compute",
                also_in: [],
                cross_in: [],
                edgar: "https://www.sec.gov/edgar/browse/?CIK=1045810",
              },
            ],
          },
        ],
      },
    ],
  },
};

describe("segment ordering by market cap", () => {
  const member = (ticker: string) => ({
    ticker,
    layerName: "Silicon",
    segmentName: "Compute",
  }) as unknown as FlatCompany;

  it("orders companies by market cap, biggest first", () => {
    const quotes = {
      NVDA: {market_cap: 5_570_000_000_000},
      AMD: {market_cap: 1_010_000_000_000},
      INTC: {market_cap: 566_000_000_000},
    };
    const sorted = [member("INTC"), member("NVDA"), member("AMD")].sort(
      compareByMarketCap(quotes),
    );

    expect(sorted.map((company) => company.ticker)).toEqual(["NVDA", "AMD", "INTC"]);
  });

  it("keeps companies without a market cap last", () => {
    const quotes = {
      NVDA: {market_cap: 5_570_000_000_000},
      AMD: {},
      INTC: {market_cap: null},
    };
    const sorted = [member("AMD"), member("NVDA"), member("INTC")].sort(
      compareByMarketCap(quotes),
    );

    expect(sorted.map((company) => company.ticker)).toEqual(["NVDA", "AMD", "INTC"]);
  });

  it("leaves catalog order intact when no quote is cached at all", () => {
    const sorted = [member("VRT"), member("NVDA")].sort(compareByMarketCap({}));

    expect(sorted.map((company) => company.ticker)).toEqual(["VRT", "NVDA"]);
  });
});

describe("column label truncation", () => {
  // Deterministic stand-in for canvas measureText: 6px per character.
  const widthOf = (text: string): number => text.length * 6;

  it("leaves a label alone when it already fits", () => {
    expect(fitText("NVIDIA", 400, widthOf)).toBe("NVIDIA");
    expect(fitText("", 400, widthOf)).toBe("");
  });

  it("keeps the longest prefix that fits and marks the cut with an ellipsis", () => {
    const full = "Constellation Energy";
    const fitted = fitText(full, 90, widthOf);

    expect(fitted.endsWith("…")).toBe(true);
    expect(full.startsWith(fitted.slice(0, -1))).toBe(true);
  });

  it("never exceeds the space it was given, counting the ellipsis", () => {
    for (const maxWidth of [0, 7, 30, 61, 90, 121, 200]) {
      expect(widthOf(fitText("Constellation Energy", maxWidth, widthOf))).toBeLessThanOrEqual(
        Math.max(maxWidth, 6),
      );
    }
  });

  it("widens the label as more room is given", () => {
    const full = "Constellation Energy";

    expect(fitText(full, 400, widthOf).length).toBeGreaterThan(
      fitText(full, 60, widthOf).length,
    );
  });

  it("degrades to a bare ellipsis rather than overflowing at zero width", () => {
    expect(fitText("Constellation Energy", 0, widthOf)).toBe("…");
  });
});

describe("market cap formatting", () => {
  it("matches the directory page's compact scale", () => {
    expect(formatCompactUSD(5_570_000_000_000)).toBe("$5.57T");
    expect(formatCompactUSD(93_833_165_760)).toBe("$93.83B");
    expect(formatCompactUSD(1_500_000)).toBe("$1.5M");
    expect(formatCompactUSD(950)).toBe("$950");
  });

  it("falls back to a placeholder when no quote is cached", () => {
    expect(formatCompactUSD(null)).toBe("—");
  });
});

describe("price formatting", () => {
  it("matches the directory page's currency format with separators", () => {
    expect(formatPrice(230.48)).toBe("$230.48");
    expect(formatPrice(1030.91)).toBe("$1,030.91");
    expect(formatPrice(1783.31)).toBe("$1,783.31");
  });

  it("falls back to a placeholder when the close is missing", () => {
    expect(formatPrice(null)).toBe("—");
    expect(formatPrice(undefined)).toBe("—");
  });
});

describe("AI layer hierarchy", () => {
  it("flattens root to layer, segment, and company records", () => {
    const result = flattenLayers(fixture);

    expect(result.layers).toHaveLength(1);
    expect(result.segments[0].layerId).toBe("silicon");
    expect(result.companies[0].ticker).toBe("NVDA");
    expect(result.companies[0].layerName).toBe("Silicon");
  });

  it("collapsing one segment does not collapse its sibling", () => {
    const state = createCollapseState();
    state.toggleSegment("silicon/compute");

    expect(state.isSegmentCollapsed("silicon/compute")).toBe(true);
    expect(state.isSegmentCollapsed("silicon/memory")).toBe(false);
  });

  it("tracks layer collapse independently from segment collapse", () => {
    const state = createCollapseState();
    state.toggleLayer("silicon");

    expect(state.isLayerCollapsed("silicon")).toBe(true);
    expect(state.isSegmentCollapsed("silicon/compute")).toBe(false);
  });
});

describe("daily change formatting", () => {
  it("matches the directory page's signed two-decimal format", () => {
    expect(formatChangePct(1.34)).toBe("+1.34%");
    expect(formatChangePct(-2.1)).toBe("-2.10%");
    expect(formatChangePct(0)).toBe("0.00%");
  });

  it("falls back to a placeholder when no quote is cached", () => {
    expect(formatChangePct(null)).toBe("—");
    expect(formatChangePct(undefined)).toBe("—");
  });

  it("maps a change to its direction class and fill", () => {
    expect(changeDirection(1.34)).toEqual({name: "up", fill: "#68d391"});
    expect(changeDirection(-2.1)).toEqual({name: "down", fill: "#fc8181"});
    expect(changeDirection(0)).toEqual({name: "flat", fill: "#8b96c2"});
    expect(changeDirection(null)).toEqual({name: "flat", fill: "#8b96c2"});
  });
});

describe("layer company detail card", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <svg id="view" viewBox="0 0 1200 800" aria-label="AI company layers visualization"></svg>
      <pre id="mermaid" hidden></pre>
      <small id="gen-time"></small>
      <span id="stats"></span>
      <span id="hint"></span>
      <div id="legend-rows"></div>
      <button id="legend-toggle" type="button" aria-expanded="true" aria-controls="legend-rows">Layers</button>
      <input type="search" id="search">
      <button id="card-close" type="button">close</button>
      <aside id="card" hidden>
        <h2 id="card-name"></h2>
        <div id="card-path"></div>
        <p id="card-desc"></p>
        <div id="card-badges"></div>
        <div id="card-meta"></div>
      </aside>
    `;
  });

  it("shows the daily change on the card when the ticker has a quote", () => {
    mountLayers(fixture, {NVDA: {change_pct: 1.34}});
    window.__selectLayerCompany?.("NVDA");

    const badge = document.querySelector("#card-badges .price-change.up") as HTMLElement;
    expect(badge.textContent).toBe("+1.34%");
    expect((document.getElementById("card") as HTMLElement).hidden).toBe(false);
  });

  it("omits the change badge when no quote is cached", () => {
    mountLayers(fixture, {});
    window.__selectLayerCompany?.("NVDA");

    expect(document.querySelector("#card-badges .price-change")).toBeNull();
    expect(document.querySelector("#card-badges")?.textContent).toContain("Semiconductors");
  });
});
