import { apiGet, apiPost } from "../api/client";
import type {
  MarketView,
  MoverItem,
  NewsItemView,
  NewsView,
  OverviewView,
} from "../api/types";

/** Format a USD value in T/B/M human units; null → em dash. */
export function formatMarketCap(usd: number | null): string {
  if (usd == null) return "—";
  if (usd >= 1e12) return `${(usd / 1e12).toFixed(1)}T`;
  if (usd >= 1e9) return `${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6) return `${(usd / 1e6).toFixed(1)}M`;
  return usd.toLocaleString();
}

/** Quality score to one decimal; null → em dash. */
export function formatScore(score: number | null): string {
  return score == null ? "—" : score.toFixed(1);
}

/** Signed percentage; null → em dash. */
export function formatPct(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

export type Polarity = "up" | "down" | "flat";

export function polarity(pct: number | null): Polarity {
  if (pct == null || pct === 0) return "flat";
  return pct > 0 ? "up" : "down";
}

/** Compact relative time: just now / 5m / 3h / 2d / Jan 5. */
export function relativeTime(iso: string | null, nowMs: number = Date.now()): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const diff = nowMs - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h`;
  if (diff < 7 * 86_400_000) return `${Math.round(diff / 86_400_000)}d`;
  return new Date(then).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Map a series onto a horizontal polyline. Empty when fewer than two points. */
export function sparkPoints(values: number[], width = 120, height = 32): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const step = width / (values.length - 1);
  const coord = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1));
  return values
    .map((v, i) => {
      const norm = max === min ? 0.5 : (v - min) / (max - min);
      const y = height - norm * height;
      return `${coord(i * step)},${coord(y)}`;
    })
    .join(" ");
}

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

export function buildIndicatorTiles(view: OverviewView): HTMLDListElement {
  const dl = el("dl", "indicator-grid");
  const tile = (label: string, value: string, sub?: string) => {
    const div = el("div", "indicator-tile");
    div.append(el("dt", undefined, label), el("dd", undefined, value));
    if (sub) div.append(el("p", "tile-sub", sub));
    dl.append(div);
  };

  tile("Companies", String(view.total_companies));
  tile("Tier 1", String(view.tiers["1"]), "Core");
  tile("Tier 2", String(view.tiers["2"]), "Major");
  tile("Tier 3", String(view.tiers["3"]), "Watch");
  tile("Total mkt cap", formatMarketCap(view.total_market_cap));
  tile("Avg quality", formatScore(view.avg_quality_score));
  return dl;
}

function moverRow(item: MoverItem): HTMLLIElement {
  const li = el("li");
  const a = el("a", "mover-row");
  a.href = `company.html?ticker=${encodeURIComponent(item.ticker)}`;
  a.append(
    el("span", "m-ticker", item.ticker),
    el("span", "m-name", item.name),
    el("span", "m-price", item.price == null ? "—" : item.price.toFixed(2)),
    el("span", `m-change ${polarity(item.change_pct)}`, formatPct(item.change_pct)),
  );
  li.append(a);
  return li;
}

export function buildMovers(view: OverviewView): HTMLDivElement {
  const wrap = el("div", "movers-grid");
  const column = (title: string, side: "up" | "down", items: MoverItem[]) => {
    const col = el("div", `mover-col ${side}`);
    col.append(el("h3", undefined, title), el("ul", "mover-list"));
    const list = col.querySelector("ul")!;
    items.forEach((item) => list.append(moverRow(item)));
    wrap.append(col);
  };
  column("Gainers", "up", view.gainers);
  column("Losers", "down", view.losers);
  return wrap;
}

export function buildMarketCards(view: MarketView): HTMLDivElement {
  const wrap = el("div", "market-grid");
  for (const index of view.indices) {
    const card = el("div", "market-card");
    card.append(
      el("div", "mc-label", index.label),
      el("div", "mc-value", index.close == null ? "—" : index.close.toLocaleString()),
      el("div", `mc-change ${polarity(index.change_pct)}`, formatPct(index.change_pct)),
    );
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 120 32");
    svg.setAttribute("class", "mc-spark");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    polyline.setAttribute("points", sparkPoints(index.spark));
    svg.append(polyline);
    card.append(svg);
    wrap.append(card);
  }
  return wrap;
}

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

const STATE = "data-state";

function setBusy(region: HTMLElement, message: string): void {
  region.replaceChildren(el("p", "data-state", message));
  region.removeAttribute(STATE);
}

export async function mountOverview(): Promise<void> {
  const app = document.querySelector<HTMLElement>("[data-overview-app]");
  if (!app) return;

  const indicators = app.querySelector<HTMLDivElement>("#overview-indicators")!;
  const movers = app.querySelector<HTMLDivElement>("#overview-movers")!;
  const market = app.querySelector<HTMLDivElement>("#overview-market")!;
  const newsList = app.querySelector<HTMLOListElement>("#overview-news")!;
  const newsRefresh = app.querySelector<HTMLButtonElement>("#news-refresh")!;
  const asOf = app.querySelector<HTMLParagraphElement>("#overview-as-of")!;

  setBusy(indicators, "Loading indicators…");
  setBusy(movers, "Loading movers…");
  setBusy(market, "Loading indices…");
  setBusy(newsList, "Loading news…");

  const fail = (region: HTMLElement, message: string): void => {
    setBusy(region, message);
    region.setAttribute(STATE, "error");
    newsRefresh.hidden = true;
  };

  try {
    const [ov, mk, nw] = await Promise.all([
      apiGet<OverviewView>("/api/v1/overview"),
      apiGet<MarketView>("/api/v1/market"),
      apiGet<NewsView>("/api/v1/news", new URLSearchParams({ limit: "20" })),
    ]);

    indicators.replaceChildren(buildIndicatorTiles(ov));
    indicators.removeAttribute(STATE);
    asOf.textContent = ov.as_of ? `As of ${ov.as_of}` : "";

    movers.replaceChildren(buildMovers(ov));
    movers.removeAttribute(STATE);

    market.replaceChildren(buildMarketCards(mk));
    market.removeAttribute(STATE);

    const renderNews = (view: NewsView) => {
      newsList.replaceChildren(buildNewsList(view.items));
      newsList.removeAttribute(STATE);
      newsRefresh.hidden = false;
    };
    renderNews(nw);

    newsRefresh.addEventListener("click", async () => {
      newsRefresh.disabled = true;
      newsRefresh.textContent = "Refreshing…";
      try {
        const refreshed = await apiPost<NewsView>("/api/v1/news/refresh");
        renderNews(refreshed);
      } catch {
        fail(newsList, "News refresh failed.");
      } finally {
        newsRefresh.disabled = false;
        newsRefresh.textContent = "Refresh";
      }
    });
  } catch {
    fail(indicators, "Overview unavailable.");
    fail(movers, "Movers unavailable.");
    fail(market, "Indices unavailable.");
    fail(newsList, "News unavailable.");
  }
}

if (document.querySelector("[data-overview-app]")) {
  void mountOverview();
}
