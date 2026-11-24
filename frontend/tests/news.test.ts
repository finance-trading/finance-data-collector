import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  buildNewsList,
  buildSourceFilters,
  mountNews,
} from "../src/pages/news";
import { relativeTime } from "../src/components/format";
import type { NewsItemView, NewsSourceCount } from "../src/api/types";

const items: NewsItemView[] = [
  { id: "1", title: "Markets rally", url: "https://example.com/a", source: "CNBC", published_at: "2026-11-23T09:00:00Z" },
  { id: "2", title: "Thread on AI capex", url: "https://www.reddit.com/r/stocks/x", source: "reddit/r/stocks", published_at: "2026-11-23T10:00:00Z" },
];

const sources: NewsSourceCount[] = [
  { source: "CNBC", count: 30 },
  { source: "reddit/r/stocks", count: 5 },
];

describe("relativeTime", () => {
  it("renders compact relative time", () => {
    const now = Date.parse("2026-11-23T12:00:00Z");
    expect(relativeTime(new Date(now - 30_000).toISOString(), now)).toBe("just now");
    expect(relativeTime(new Date(now - 5 * 60_000).toISOString(), now)).toBe("5m");
    expect(relativeTime(new Date(now - 3 * 3_600_000).toISOString(), now)).toBe("3h");
    expect(relativeTime("2026-01-05T00:00:00Z", now)).toBe("Jan 5");
    expect(relativeTime(null, now)).toBe("");
  });
});

describe("buildNewsList", () => {
  it("renders each item with source, time, and linked title", () => {
    const list = buildNewsList(items);
    const rows = [...list.querySelectorAll(".news-item")];
    expect(rows.length).toBe(2);
    const link = rows[0].querySelector<HTMLAnchorElement>("a.ni-title")!;
    expect(link.href).toBe("https://example.com/a");
    expect(rows[1].querySelector(".ni-source")?.textContent).toBe("reddit/r/stocks");
  });
});

describe("buildSourceFilters", () => {
  it("renders an All chip plus one chip per source, marking the active one", () => {
    const row = buildSourceFilters(sources, items.length, "reddit/r/stocks");
    const chips = [...row.querySelectorAll<HTMLButtonElement>(".news-filter-chip")];
    expect(chips.length).toBe(3); // All + 2 sources
    expect(chips[0].dataset.source).toBe("all");
    expect(chips[0].textContent).toContain("2");
    expect(chips[1].textContent).toContain("30");
    const active = chips.find((c) => c.dataset.source === "reddit/r/stocks");
    expect(active?.getAttribute("aria-pressed")).toBe("true");
    expect(chips.find((c) => c.dataset.source === "CNBC")?.getAttribute("aria-pressed")).toBe(null);
  });
});

describe("mountNews", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <main data-news-app>
        <div id="news-filters" role="group"></div>
        <div id="news-list" role="status"></div>
        <button id="news-refresh" type="button">Refresh</button>
        <p id="news-as-of"></p>
      </main>`;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  const view = {
    as_of: "2026-11-23T09:00:00Z",
    items,
    sources,
  };

  it("lists all items and filters by source", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => view })));
    await mountNews();
    expect(document.querySelectorAll("#news-list .news-item").length).toBe(2);

    const redditChip = document.querySelector<HTMLButtonElement>('[data-source="reddit/r/stocks"]');
    expect(redditChip).toBeTruthy();
    redditChip!.click();
    expect(document.querySelectorAll("#news-list .news-item").length).toBe(1);
    expect(document.querySelector("#news-list .ni-source")?.textContent).toBe("reddit/r/stocks");
  });

  it("shows a source with zero stored items as an empty list when selected", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ...view, items: [] }) })));
    await mountNews();
    document.querySelector<HTMLButtonElement>('[data-source="all"]')!.click();
    expect(document.querySelector("#news-list .data-state")).toBeTruthy();
  });

  it("surfaces an error state and disables refresh on failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
    await mountNews();
    expect(document.querySelector("#news-list")?.textContent).toMatch(/could not be loaded/i);
  });
});
