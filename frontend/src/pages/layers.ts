import * as d3 from "d3";

import { apiGet } from "../api/client";
import type {
  LayerCompanyNode,
  LayerNode,
  LayerSegmentNode,
  LayersPayload,
  QuotesPayload,
} from "../api/types";
import { renderDataState } from "../components/data-state";

export interface FlatCompany extends LayerCompanyNode {
  layerName: string;
  segmentName: string;
}

export interface FlatSegment extends LayerSegmentNode {
  layerId: string;
  layerName: string;
}

export function flattenLayers(payload: LayersPayload) {
  const segments: FlatSegment[] = [];
  const companies: FlatCompany[] = [];
  payload.root.children.forEach((layer) => {
    layer.children.forEach((segment) => {
      segments.push({...segment, layerId: layer.id, layerName: layer.name});
      segment.children.forEach((company) => {
        companies.push({
          ...company,
          layerName: layer.name,
          segmentName: segment.name,
        });
      });
    });
  });
  return {layers: payload.root.children, segments, companies};
}

export function createCollapseState() {
  const layers = new Set<string>();
  const segments = new Set<string>();
  return {
    toggleLayer(id: string): void {
      if (layers.has(id)) layers.delete(id);
      else layers.add(id);
    },
    toggleSegment(id: string): void {
      if (segments.has(id)) segments.delete(id);
      else segments.add(id);
    },
    isLayerCollapsed: (id: string): boolean => layers.has(id),
    isSegmentCollapsed: (id: string): boolean => segments.has(id),
  };
}

const palette = [
  "#f6ad55",
  "#7f8dff",
  "#4fd1c5",
  "#9f7aea",
  "#68d391",
  "#f687b3",
  "#fbd38d",
  "#63b3ed",
];

function element<T extends HTMLElement = HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing #${id}`);
  return value as T;
}

function appendText(parent: HTMLElement, className: string, value: string): HTMLElement {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = value;
  parent.append(span);
  return span;
}

/** Signed daily change, matching the directory page ("+1.34%", "-2.10%", "0.00%"). */
export function formatChangePct(changePct: number | null | undefined): string {
  if (changePct === null || changePct === undefined) return "—";
  return changePct > 0
    ? `+${changePct.toFixed(2)}%`
    : changePct < 0
      ? changePct.toFixed(2) + "%"
      : "0.00%";
}

/** Direction class and text color shared by the card, columns, and tooltips. */
export function changeDirection(changePct: number | null | undefined): {
  name: "up" | "down" | "flat";
  fill: string;
} {
  if (changePct === null || changePct === undefined || changePct === 0) {
    return {name: "flat", fill: "#8b96c2"};
  }
  return changePct > 0
    ? {name: "up", fill: "#68d391"}
    : {name: "down", fill: "#fc8181"};
}

/**
 * Order companies inside a layer or segment by market cap, biggest first.
 *
 * Companies without a cached quote keep no market cap and sort last, matching
 * `list_companies` on the directory page so both screens agree on ordering.
 * Ties fall back to catalog order because `Array.sort` is stable.
 */
export function compareByMarketCap(
  quotes: QuotesPayload["quotes"],
): (a: FlatCompany, b: FlatCompany) => number {
  const capOf = (ticker: string): number | null => quotes[ticker]?.market_cap ?? null;
  return (a, b) => {
    const left = capOf(a.ticker);
    const right = capOf(b.ticker);
    if (left === null) return right === null ? 0 : 1;
    if (right === null) return -1;
    return right - left;
  };
}

/** Market cap in millions, matching the directory page ("$5,570,000M", "$985.2M"). */
export function formatCompactUSD(value: number | null): string {
  if (value === null) return "—";
  const millions = value / 1e6;
  return millions >= 1000
    ? `$${Math.round(millions).toLocaleString("en-US")}M`
    : `$${millions.toFixed(1)}M`;
}

/** Latest close with thousands separators, matching the directory page. */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value);
}

let measurer: CanvasRenderingContext2D | null | undefined;

/** Shared 2D context for text measurement; null when canvas is unavailable. */
function canvasContext(): CanvasRenderingContext2D | null {
  if (measurer === undefined) {
    try {
      measurer = document.createElement("canvas").getContext("2d");
    } catch {
      measurer = null;
    }
  }
  return measurer;
}

/**
 * Longest prefix of `value` that fits `maxWidth` as measured by `widthOf`,
 * with an ellipsis appended when anything was dropped.
 *
 * The caller supplies the measurement so this stays a pure function: canvas
 * `measureText` in the browser, a fixed-width estimate under jsdom. Binary
 * search keeps it to O(log n) probes per label — measuring the real SVG nodes
 * instead would force a layout flush per candidate, visible as jank across 227
 * companies.
 */
export function fitText(
  value: string,
  maxWidth: number,
  widthOf: (text: string) => number,
): string {
  if (widthOf(value) <= maxWidth) return value;
  let low = 0;
  let high = value.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (widthOf(`${value.slice(0, mid)}…`) <= maxWidth) low = mid;
    else high = mid - 1;
  }
  return `${value.slice(0, low)}…`;
}

export function mountLayers(
  payload: LayersPayload,
  quotes: QuotesPayload["quotes"] = {},
): void {
  const {layers, companies} = flattenLayers(payload);
  const byTicker = new Map(companies.map((company) => [company.ticker, company] as const));
  const changeOf = (ticker: string): number | null | undefined => quotes[ticker]?.change_pct;
  const colorOf = new Map(
    layers.map((layer, index) => [layer.id, palette[index % palette.length]] as const),
  );
  const hidden = new Set<string>();
  const collapse = createCollapseState();
  let mode: "columns" | "tree" | "mermaid" = "columns";
  let contentSize = {width: 1200, height: 600};
  let needsFit = true;

  const svg = d3.select<SVGSVGElement, unknown>("#view");
  const chart = svg.append("g");

  const query = (): string => element<HTMLInputElement>("search").value.trim().toLocaleLowerCase();
  const matches = (company: FlatCompany): boolean => {
    const needle = query();
    if (!needle) return true;
    return [
      company.ticker,
      company.name,
      company.description,
      company.layerName,
      company.segmentName,
      company.industry,
      company.sector,
      ...company.cross_in,
    ].join(" ").toLocaleLowerCase().includes(needle);
  };
  const visible = (company: FlatCompany): boolean =>
    !hidden.has(company.layer) && matches(company);

  const showCard = (company: FlatCompany): void => {
    element("card-name").textContent = `${company.name} (${company.ticker})`;
    element("card-path").textContent = `${company.layerName} · ${company.segmentName}`;
    element("card-desc").textContent = company.description;
    const badges = element("card-badges");
    badges.replaceChildren();
    appendText(badges, "badge", company.industry);
    const changePct = changeOf(company.ticker);
    if (changePct !== null && changePct !== undefined) {
      appendText(
        badges,
        `badge price-change ${changeDirection(changePct).name}`,
        formatChangePct(changePct),
      );
    }
    company.cross_in.forEach((name) => appendText(badges, "badge cross", `Cross-layer: ${name}`));
    const meta = element("card-meta");
    meta.replaceChildren();
    appendText(meta, "", `CIK ${company.cik} · ${company.sector} · `);
    const link = document.createElement("a");
    link.href = company.edgar;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "EDGAR filing";
    meta.append(link);
    element("card").hidden = false;
  };

  const byMarketCap = compareByMarketCap(quotes);

  const companiesFor = (layer: LayerNode, segment?: LayerSegmentNode): FlatCompany[] =>
    companies
      .filter(
        (company) =>
          company.layer === layer.id &&
          (!segment || company.segment === segment.name) &&
          visible(company),
      )
      .sort(byMarketCap);

  const renderColumns = (): void => {
    const columnWidth = 236;
    // Two lines per company: identity on top (dot, ticker, name), the three
    // numbers below (price, market cap, daily change).  One line cannot hold
    // this many fields without starving the company name.
    const rowHeight = 38;
    const segmentHeight = 28;
    const top = 132;
    // The name owns the full width of line 1, so only its left inset matters.
    const nameFont =
      '11.5px "Avenir Next", Avenir, system-ui, -apple-system, BlinkMacSystemFont, sans-serif';
    const tickerX = 11;
    const nameX = 56;
    const valueRight = columnWidth - 12;
    const nameMaxWidth = valueRight - 8 - nameX;
    // Widest price in the universe is "$1,783.31"; the fixed offset keeps the
    // market-cap column aligned down the layer instead of ragged per row.
    const capX = nameX + 58;
    const identityY = -4;
    const valueY = 11;
    const context = canvasContext();
    // 6.4px per character slightly overstates Avenir Next's average advance at
    // 11.5px, so the no-canvas fallback truncates a little early rather than
    // letting a name reach into the change column.
    const labelWidth = context
      ? (text: string): number => {
          context.font = nameFont;
          return context.measureText(text).width;
        }
      : (text: string): number => text.length * 6.4;
    chart.selectAll("*").remove();
    let maxBottom = 440;

    layers.forEach((layer, index) => {
      const x = 42 + index * columnWidth;
      const color = colorOf.get(layer.id) ?? palette[0];
      const layerCompanies = companiesFor(layer);
      const layerCollapsed = collapse.isLayerCollapsed(layer.id);
      const header = chart.append("g")
        .attr("data-layer-id", layer.id)
        .attr("tabindex", 0)
        .attr("role", "button")
        .style("cursor", "pointer")
        .on("click", () => {
          collapse.toggleLayer(layer.id);
          render();
        });
      header.append("rect")
        .attr("x", x - 14).attr("y", 58).attr("width", columnWidth - 28).attr("height", 48)
        .attr("rx", 9).attr("fill", `${color}1f`).attr("stroke", `${color}66`)
        .append("title").text(layer.summary);
      header.append("text").attr("x", x).attr("y", 80).attr("fill", color)
        .style("font-size", "13px").style("font-weight", "600")
        .text(`${layerCollapsed ? "▸" : "▾"} ${layer.name} (${layerCompanies.length})`);
      header.append("text").attr("x", x).attr("y", 97).attr("fill", "#7f8ab5")
        .style("font-size", "10.5px").text(layer.name_en);

      let y = top;
      if (!layerCollapsed) {
        layer.children.forEach((segment) => {
          const members = companiesFor(layer, segment);
          if (!members.length) return;
          const segmentCollapsed = collapse.isSegmentCollapsed(segment.id);
          const segmentGroup = chart.append("g")
            .attr("data-segment-id", segment.id)
            .attr("tabindex", 0)
            .attr("role", "button")
            .style("cursor", "pointer")
            .on("click", () => {
              collapse.toggleSegment(segment.id);
              render();
            });
          segmentGroup.append("text").attr("x", x).attr("y", y + 12).attr("fill", "#8b96c2")
            .style("font-size", "11px")
            .text(`${segmentCollapsed ? "▸" : "▾"} ${segment.name} · ${members.length}`);
          y += segmentHeight;
          if (!segmentCollapsed) {
            members.forEach((company) => {
              const cy = y + rowHeight / 2;
              const node = chart.append("g")
                .attr("data-company-ticker", company.ticker)
                .style("cursor", "pointer")
                .on("click", () => showCard(company));
              node.append("circle").attr("cx", x).attr("cy", cy).attr("r", 5)
                .attr("fill", color).attr("stroke", "#0a0e1a");
              node.append("text").attr("x", x + tickerX).attr("y", cy + identityY).attr("fill", "#e6ecff")
                .style("font-size", "12px").text(company.ticker);
              node.append("text").attr("x", x + nameX).attr("y", cy + identityY).attr("fill", "#8b96c2")
                .style("font-size", "11.5px")
                .text(fitText(company.name, nameMaxWidth, labelWidth));
              const changePct = changeOf(company.ticker);
              const marketCap = quotes[company.ticker]?.market_cap ?? null;
              node.append("text").attr("x", x + nameX).attr("y", cy + valueY).attr("fill", "#cbd5ff")
                .style("font-size", "10.5px")
                .text(formatPrice(quotes[company.ticker]?.price));
              node.append("text").attr("x", x + capX).attr("y", cy + valueY).attr("fill", "#6b76a0")
                .style("font-size", "10.5px")
                .text(formatCompactUSD(marketCap));
              node.append("text")
                .attr("x", x + valueRight).attr("y", cy + valueY).attr("text-anchor", "end")
                .attr("fill", changeDirection(changePct).fill)
                .style("font-size", "11px")
                .text(formatChangePct(changePct));
              node
                .append("title")
                .text(
                  `${company.ticker} ${company.name}\n${company.description}` +
                    (quotes[company.ticker]?.price === null ||
                    quotes[company.ticker]?.price === undefined
                      ? "\nPrice: no quote cached"
                      : `\nPrice: ${formatPrice(quotes[company.ticker]?.price)}`) +
                    (marketCap === null
                      ? "\nMarket cap: no quote cached"
                      : `\nMarket cap: ${formatCompactUSD(marketCap)}`) +
                    (changePct === null || changePct === undefined
                      ? ""
                      : `\nDaily change: ${formatChangePct(changePct)}`),
                );
              y += rowHeight;
            });
          }
        });
      }
      maxBottom = Math.max(maxBottom, y + 60);
    });

    contentSize = {width: 70 + layers.length * columnWidth, height: maxBottom};
  };

  const renderTree = (): void => {
    chart.selectAll("*").remove();
    const rowHeight = 28;
    const depthWidth = 280;
    let row = 0;
    const positions = new Map<string, {x: number; y: number; parent?: string}>();
    positions.set(payload.root.id, {x: 30, y: 50});
    row += 1;
    layers.filter((layer) => !hidden.has(layer.id)).forEach((layer) => {
      const layerKey = `layer:${layer.id}`;
      positions.set(layerKey, {x: 30 + depthWidth, y: 50 + row * rowHeight, parent: payload.root.id});
      row += 1;
      if (collapse.isLayerCollapsed(layer.id)) return;
      layer.children.forEach((segment) => {
        const members = companiesFor(layer, segment);
        if (!members.length) return;
        const segmentKey = `segment:${segment.id}`;
        positions.set(segmentKey, {x: 30 + depthWidth * 2, y: 50 + row * rowHeight, parent: layerKey});
        row += 1;
        if (collapse.isSegmentCollapsed(segment.id)) return;
        members.forEach((company) => {
          positions.set(`company:${company.ticker}`, {
            x: 30 + depthWidth * 3,
            y: 50 + row * rowHeight,
            parent: segmentKey,
          });
          row += 1;
        });
      });
    });

    positions.forEach((position) => {
      if (!position.parent) return;
      const parent = positions.get(position.parent);
      if (!parent) return;
      chart.append("path")
        .attr("d", `M${parent.x},${parent.y} C${parent.x + 80},${parent.y} ${position.x - 80},${position.y} ${position.x},${position.y}`)
        .attr("fill", "none").attr("stroke", "#4c5b91").attr("stroke-opacity", 0.65);
    });
    positions.forEach((position, key) => {
      const company = key.startsWith("company:") ? byTicker.get(key.slice(8)) : undefined;
      const layer = key.startsWith("layer:") ? layers.find((item) => item.id === key.slice(6)) : undefined;
      const segment = key.startsWith("segment:")
        ? layers.flatMap((item) => item.children).find((item) => item.id === key.slice(8))
        : undefined;
      const companyChange = company ? formatChangePct(changeOf(company.ticker)) : null;
      const label = company
        ? `${company.ticker} ${company.name}${companyChange === "—" ? "" : ` (${companyChange})`}`
        : layer
          ? `${collapse.isLayerCollapsed(layer.id) ? "▸" : "▾"} ${layer.name} (${layer.count})`
          : segment
            ? `${collapse.isSegmentCollapsed(segment.id) ? "▸" : "▾"} ${segment.name} (${segment.count})`
            : `${payload.root.name} (${payload.root.count})`;
      const node = chart.append("g").style("cursor", company || layer || segment ? "pointer" : "default")
        .on("click", () => {
          if (company) showCard(company);
          else if (layer) collapse.toggleLayer(layer.id);
          else if (segment) collapse.toggleSegment(segment.id);
          if (layer || segment) render();
        });
      node.append("circle").attr("cx", position.x).attr("cy", position.y).attr("r", company ? 4 : 5.5)
        .attr("fill", company ? colorOf.get(company.layer) ?? palette[0] : "#9db4ff");
      node.append("text").attr("x", position.x + 11).attr("y", position.y + 4)
        .attr("fill", company ? "#cbd5ff" : "#fff")
        .style("font-size", company ? "11.5px" : "12.5px").text(label);
    });
    contentSize = {width: depthWidth * 3 + 430, height: Math.max(440, 100 + row * rowHeight)};
  };

  const mermaidText = (): string => {
    const lines = ["graph LR", `  R[\"${payload.root.name} (${payload.root.count})\"]`];
    layers.forEach((layer, layerIndex) => {
      if (hidden.has(layer.id)) return;
      lines.push(`  L${layerIndex}[\"${layer.name} · ${layer.name_en} (${layer.count})\"]`);
      lines.push(`  R --> L${layerIndex}`);
      layer.children.forEach((segment, segmentIndex) => {
        const members = companiesFor(layer, segment);
        if (!members.length) return;
        lines.push(`  L${layerIndex}S${segmentIndex}[\"${segment.name} (${members.length})\"]`);
        lines.push(`  L${layerIndex} --> L${layerIndex}S${segmentIndex}`);
        members.forEach((company) => {
          const id = `n_${company.ticker.replace(/[^A-Za-z0-9]/g, "_")}`;
          const companyChange = formatChangePct(changeOf(company.ticker));
          const changeSuffix = companyChange === "—" ? "" : ` (${companyChange})`;
          lines.push(`  ${id}[\"${company.ticker} ${company.name}${changeSuffix}\"]`);
          lines.push(`  L${layerIndex}S${segmentIndex} --> ${id}`);
        });
      });
    });
    return lines.join("\n");
  };

  /**
 * Scale the drawing to the available width and give the SVG the height the
 * scaled content actually needs.
 *
 * There is no interactive zoom or pan, and 227 companies laid out in six columns
 * come to roughly 4100px — far taller than any viewport. Scaling to *height* as
 * well would shrink the labels to about 3px, so the width sets the scale (capped
 * at 1: never enlarge small layouts) and the page scrolls for the rest.
 */
const fit = (): void => {
    const node = svg.node();
    if (!node) return;
    const width = node.parentElement?.clientWidth ?? node.clientWidth;
    const scale = Math.min(1, width / contentSize.width);
    svg.attr("width", width).attr("height", Math.ceil(contentSize.height * scale));
    chart.attr(
      "transform",
      `translate(${(width - contentSize.width * scale) / 2},0) scale(${scale})`,
    );
  };

  const render = (): void => {
    const mermaid = element("mermaid");
    if (mode === "mermaid") {
      mermaid.textContent = mermaidText();
      return;
    }
    if (mode === "tree") renderTree();
    else renderColumns();
    if (needsFit) {
      fit();
      needsFit = false;
    }
  };

  element("gen-time").textContent = payload.generated_at ? ` · ${payload.generated_at}` : "";
  element("stats").textContent =
    `${payload.stats.companies} companies · ${payload.stats.layers} layers · ` +
    `${payload.stats.segments} segments · ${payload.stats.cross_layer} cross-layer roles`;
  element("hint").textContent =
    "Click a company for details · click a layer or segment title to collapse";

  const legendToggle = element<HTMLButtonElement>("legend-toggle");
  const legendRows = element("legend-rows");
  legendToggle.addEventListener("click", () => {
    const expanded = legendToggle.getAttribute("aria-expanded") !== "true";
    legendToggle.setAttribute("aria-expanded", String(expanded));
    legendRows.hidden = !expanded;
  });
  layers.forEach((layer) => {
    const row = document.createElement("label");
    row.className = "row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) hidden.delete(layer.id);
      else hidden.add(layer.id);
      needsFit = true;
      render();
    });
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = colorOf.get(layer.id) ?? palette[0];
    row.append(checkbox, dot);
    appendText(row, "", layer.name);
    appendText(row, "n", String(layer.count));
    legendRows.append(row);
  });

  element<HTMLInputElement>("search").addEventListener("input", () => {
    needsFit = true;
    render();
  });
  document.querySelectorAll<HTMLButtonElement>("button.mode").forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.mode;
      mode = value === "tree" || value === "mermaid" ? value : "columns";
      document.querySelectorAll("button.mode").forEach((other) =>
        other.classList.toggle("active", other === button),
      );
      element("mermaid").hidden = mode !== "mermaid";
      element("view").toggleAttribute("hidden", mode === "mermaid");
      // Each mode is a different document of very different length; carrying the
      // previous scroll offset over would land mid-content under the topbar.
      window.scrollTo(0, 0);
      needsFit = true;
      render();
    });
  });
  element<HTMLButtonElement>("card-close").addEventListener("click", () => {
    element("card").hidden = true;
  });
  window.addEventListener("resize", () => {
    needsFit = true;
    render();
  });
  window.__selectLayerCompany = (ticker: string) => {
    const company = byTicker.get(ticker);
    if (company) showCard(company);
  };
  render();
}

async function loadLayers(): Promise<void> {
  const status = element("layers-state");
  renderDataState(status, "loading", "Reading the AI industry layers…");
  try {
    const [payload, quotes] = await Promise.all([
      apiGet<LayersPayload>("/api/v1/visualizations/layers"),
      apiGet<QuotesPayload>("/api/v1/quotes").catch(() => ({
        generated_at: null,
        quotes: {},
      })) as Promise<QuotesPayload>,
    ]);
    mountLayers(payload, quotes.quotes);
    renderDataState(status, "ready", "");
  } catch (error) {
    renderDataState(
      status,
      "error",
      "The AI industry layers are unavailable. " +
        "Confirm the visualization data has been generated.",
      () => void loadLayers(),
    );
    console.error(error);
  }
}

declare global {
  interface Window {
    __selectLayerCompany?: (ticker: string) => void;
  }
}

if (document.querySelector("[data-layers-app]")) {
  void loadLayers();
}
