import { describe, expect, it } from "vitest";

import { createCollapseState, flattenLayers } from "../src/pages/layers";
import type { LayersPayload } from "../src/api/types";

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
