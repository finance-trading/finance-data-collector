import { describe, expect, it } from "vitest";

import { degreeByTicker, normalizeGraph } from "../src/pages/graph";
import type { GraphPayload } from "../src/api/types";

describe("graph normalization", () => {
  it("normalizes numeric link endpoints to ticker identity", () => {
    const graph = normalizeGraph({
      generated_at: "test",
      nodes: [{id: 1045810, ticker: "NVDA", name: "NVIDIA"}],
      links: [{source: 1045810, target: 1045810, type: "industry", weight: 1}],
    });

    expect(graph.links[0]).toMatchObject({source: "NVDA", target: "NVDA"});
  });

  it("counts degree by ticker rather than CIK", () => {
    const graph: GraphPayload = {
      generated_at: "test",
      nodes: [
        {id: 1652044, ticker: "GOOG", name: "Alphabet Class C"},
        {id: 1652045, ticker: "GOOGL", name: "Alphabet Class A"},
      ],
      links: [
        {source: 1652044, target: 1652045, type: "industry", weight: 1},
      ],
    };

    expect(degreeByTicker(normalizeGraph(graph))).toEqual({GOOG: 1, GOOGL: 1});
  });

  it("preserves an already normalized ticker endpoint", () => {
    const graph: GraphPayload = {
      generated_at: "test",
      nodes: [{id: 1045810, ticker: "NVDA", name: "NVIDIA"}],
      links: [{source: "NVDA", target: "NVDA", type: "crossref", weight: 2}],
    };

    expect(normalizeGraph(graph).links[0].source).toBe("NVDA");
  });
});
