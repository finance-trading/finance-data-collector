import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const frontendRoot = resolve(import.meta.dirname, "..");

describe("multi-page frontend", () => {
  it.each(["index.html", "companies.html", "news.html", "company.html", "layers.html"])(
    "includes the %s Vite entry",
    (name) => {
      expect(readFileSync(resolve(frontendRoot, name), "utf8")).toContain(
        '<meta name="viewport"',
      );
    },
  );

  it("keeps layout classes off the overview market mount point", () => {
    // Rendered content owns .market-sections; a grid class here would shrink it
    // to one grid item.
    const html = readFileSync(resolve(frontendRoot, "index.html"), "utf8");
    const mount = html.match(/<div id="overview-market"[^>]*>/)?.[0];
    expect(mount).toBeTruthy();
    expect(mount).not.toContain("market-grid");
  });
});
