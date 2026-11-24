import { apiGet, apiPost } from "../api/client";
import { relativeTime } from "../components/format";
import type {
  NewsItemView,
  NewsSourceCount,
  NewsView,
} from "../api/types";

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** A `<ol>` of news items: source badge, relative time, and linked title. */
export function buildNewsList(items: NewsItemView[]): HTMLOListElement {
  const ol = el("ol", "news-list");
  for (const item of items) {
    const li = el("li", "news-item");
    const top = el("div", "ni-top");
    top.append(el("span", "ni-source", item.source), el("span", "ni-time", relativeTime(item.published_at)));
    const link = el("a", "ni-title", item.title);
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    li.append(top, link);
    ol.append(li);
  }
  return ol;
}

/** Source filter chips (All + one per source with its count). */
export function buildSourceFilters(
  sources: NewsSourceCount[],
  allCount: number,
  active: string,
): HTMLDivElement {
  const row = el("div", "news-filters");
  const chip = (label: string, count: number, value: string) => {
    const button = el("button", "news-filter-chip");
    button.type = "button";
    button.dataset.source = value;
    if (value === active) button.setAttribute("aria-pressed", "true");
    button.append(el("span", "nf-label", label), el("span", "nf-count", String(count)));
    row.append(button);
  };
  chip("All", allCount, "all");
  for (const source of sources) {
    chip(source.source, source.count, source.source);
  }
  return row;
}

export async function mountNews(): Promise<void> {
  const app = document.querySelector<HTMLElement>("[data-news-app]");
  if (!app) return;

  const filters = app.querySelector<HTMLDivElement>("#news-filters")!;
  const list = app.querySelector<HTMLDivElement>("#news-list")!;
  const refresh = app.querySelector<HTMLButtonElement>("#news-refresh")!;
  const asOf = app.querySelector<HTMLParagraphElement>("#news-as-of")!;

  let items: NewsItemView[] = [];
  let sources: NewsSourceCount[] = [];
  let active = "all";

  const setBusy = (message: string): void => {
    list.replaceChildren(el("p", "data-state", message));
    list.removeAttribute("data-state");
  };

  const render = (): void => {
    filters.replaceChildren(buildSourceFilters(sources, items.length, active));
    const shown = active === "all" ? items : items.filter((item) => item.source === active);
    const ol = buildNewsList(shown);
    if (!shown.length) {
      ol.append(el("li", "data-state", "No news items yet. Run a refresh to collect from the feeds."));
    }
    list.replaceChildren(ol);
  };

  const load = async (): Promise<void> => {
    setBusy("Loading news…");
    try {
      const view = await apiGet<NewsView>("/api/v1/news", new URLSearchParams({ per_source: "8" }));
      items = view.items;
      sources = view.sources ?? [];
      active = "all";
      render();
      if (view.as_of) asOf.textContent = `Collected ${relativeTime(view.as_of)} · ${sources.length} source${sources.length === 1 ? "" : "s"}`;
    } catch {
      setBusy("News could not be loaded.");
      list.setAttribute("data-state", "error");
    }
  };

  filters.addEventListener("click", (event) => {
    const target = (event.target as Element).closest<HTMLButtonElement>("[data-source]");
    if (!target) return;
    active = target.dataset.source ?? "all";
    render();
  });

  refresh.addEventListener("click", async () => {
    refresh.disabled = true;
    refresh.textContent = "Refreshing…";
    try {
      const view = await apiPost<NewsView>("/api/v1/news/refresh");
      items = view.items;
      sources = view.sources ?? [];
      active = "all";
      render();
      if (view.as_of) asOf.textContent = `Collected ${relativeTime(view.as_of)} · ${sources.length} source${sources.length === 1 ? "" : "s"}`;
    } catch {
      setBusy("News refresh failed.");
      list.setAttribute("data-state", "error");
    } finally {
      refresh.disabled = false;
      refresh.textContent = "Refresh";
    }
  });

  await load();
}

if (document.querySelector("[data-news-app]")) {
  void mountNews();
}
