import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const frontendRoot = resolve(import.meta.dirname, "..");

describe("multi-page frontend", () => {
  it.each(["index.html", "company.html", "graph.html", "layers.html"])(
    "includes the %s Vite entry",
    (name) => {
      expect(readFileSync(resolve(frontendRoot, name), "utf8")).toContain(
        '<meta name="viewport"',
      );
    },
  );
});
