import * as d3 from "d3";

import { apiGet } from "../api/client";
import type {
  LayerCompanyNode,
  LayerNode,
  LayerSegmentNode,
  LayersPayload,
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

export function mountLayers(payload: LayersPayload): void {
  const {layers, companies} = flattenLayers(payload);
  const byTicker = new Map(companies.map((company) => [company.ticker, company] as const));
  const colorOf = new Map(
    layers.map((layer, index) => [layer.id, palette[index % palette.length]] as const),
  );
  const hidden = new Set<string>();
  const collapse = createCollapseState();
  let mode: "columns" | "tree" | "mermaid" = "columns";
  let showCross = true;
  let contentSize = {width: 1200, height: 600};
  let needsFit = true;

  const svg = d3.select<SVGSVGElement, unknown>("#view");
  const chart = svg.append("g");
  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.2, 2.5])
    .on("zoom", (event) => chart.attr("transform", event.transform.toString()));
  svg.call(zoom);

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

  const companiesFor = (layer: LayerNode, segment?: LayerSegmentNode): FlatCompany[] =>
    companies.filter(
      (company) =>
        company.layer === layer.id &&
        (!segment || company.segment === segment.name) &&
        visible(company),
    );

  const renderColumns = (): void => {
    const columnWidth = 218;
    const rowHeight = 30;
    const segmentHeight = 25;
    const top = 132;
    chart.selectAll("*").remove();
    const positions = new Map<string, [number, number]>();
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
              positions.set(company.ticker, [x, cy]);
              const node = chart.append("g")
                .attr("data-company-ticker", company.ticker)
                .style("cursor", "pointer")
                .on("click", () => showCard(company));
              node.append("circle").attr("cx", x).attr("cy", cy).attr("r", 5)
                .attr("fill", color).attr("stroke", "#0a0e1a");
              node.append("text").attr("x", x + 12).attr("y", cy + 4).attr("fill", "#e6ecff")
                .style("font-size", "12px").text(company.ticker);
              node.append("text").attr("x", x + 58).attr("y", cy + 4).attr("fill", "#8b96c2")
                .style("font-size", "11.5px")
                .text(company.name.length > 20 ? `${company.name.slice(0, 19)}…` : company.name);
              node.append("title").text(`${company.ticker} ${company.name}\n${company.description}`);
              y += rowHeight;
            });
          }
        });
      }
      maxBottom = Math.max(maxBottom, y + 60);
    });

    if (showCross) {
      positions.forEach(([x, y], ticker) => {
        const company = byTicker.get(ticker);
        company?.also_in.filter((id) => !hidden.has(id)).forEach((targetId) => {
          const targetIndex = layers.findIndex((layer) => layer.id === targetId);
          if (targetIndex < 0) return;
          const targetX = 42 + targetIndex * columnWidth;
          chart.append("path")
            .attr("d", `M${x + 7},${y} C${x + 50},${y} ${targetX - 50},${top - 34} ${targetX - 2},${top - 34}`)
            .attr("fill", "none").attr("stroke", "#f6ad55").attr("stroke-opacity", 0.45)
            .attr("stroke-dasharray", "4 4").attr("stroke-width", 1.1);
        });
      });
    }
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
      const label = company
        ? `${company.ticker} ${company.name}`
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
    const cross: string[] = [];
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
          lines.push(`  ${id}[\"${company.ticker} ${company.name}\"]`);
          lines.push(`  L${layerIndex}S${segmentIndex} --> ${id}`);
          company.also_in.forEach((target) => {
            const targetIndex = layers.findIndex((item) => item.id === target);
            if (targetIndex >= 0) cross.push(`  ${id} -.-> L${targetIndex}`);
          });
        });
      });
    });
    return [...lines, ...cross].join("\n");
  };

  const fit = (): void => {
    const node = svg.node();
    if (!node) return;
    const box = node.getBoundingClientRect();
    svg.attr("width", box.width).attr("height", box.height);
    const fitScale = Math.min(box.width / contentSize.width, box.height / contentSize.height);
    const scale = Math.min(1.25, Math.max(fitScale, 0.85));
    const tx = (box.width - contentSize.width * scale) / 2;
    const ty = 40 - 48 * scale;
    svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
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
    "Click a company for details · click a layer or segment title to collapse · scroll to zoom · drag to pan";

  const legendRows = element("legend-rows");
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

  element<HTMLInputElement>("show-cross").addEventListener("change", (event) => {
    showCross = (event.currentTarget as HTMLInputElement).checked;
    render();
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
    const payload = await apiGet<LayersPayload>("/api/v1/visualizations/layers");
    mountLayers(payload);
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
