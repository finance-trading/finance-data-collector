import ThreeForceGraph, { type ForceGraph3DInstance } from "3d-force-graph";

import { apiGet } from "../api/client";
import type { GraphEndpoint, GraphLink, GraphNode, GraphPayload } from "../api/types";
import { renderDataState } from "../components/data-state";

const palette = [
  "#7f8dff",
  "#4fd1c5",
  "#f6ad55",
  "#fc8181",
  "#9f7aea",
  "#68d391",
  "#f687b3",
  "#4299e1",
  "#fbd38d",
  "#63b3ed",
];

const linkColors: Record<string, string> = {
  industry: "#3a4a80",
  crossref: "#f6ad55",
  coholding: "#4fd1c5",
  "industry+crossref": "#f59e0b",
};

function endpointTicker(
  endpoint: GraphEndpoint,
  tickerById: ReadonlyMap<string, string>,
): string {
  if (typeof endpoint === "object") return endpoint.ticker;
  const value = String(endpoint);
  return tickerById.get(value) ?? value;
}

export function normalizeGraph(payload: GraphPayload): GraphPayload {
  const tickerById = new Map(
    payload.nodes.map((node) => [String(node.id), node.ticker] as const),
  );
  return {
    ...payload,
    nodes: payload.nodes.map((node) => ({...node})),
    links: payload.links.map((link) => ({
      ...link,
      source: endpointTicker(link.source, tickerById),
      target: endpointTicker(link.target, tickerById),
    })),
  };
}

export function degreeByTicker(graph: GraphPayload): Record<string, number> {
  const tickerById = new Map(
    graph.nodes.map((node) => [String(node.id), node.ticker] as const),
  );
  return graph.links.reduce<Record<string, number>>((degree, link) => {
    const source = endpointTicker(link.source, tickerById);
    const target = endpointTicker(link.target, tickerById);
    degree[source] = (degree[source] ?? 0) + 1;
    degree[target] = (degree[target] ?? 0) + 1;
    return degree;
  }, {});
}

function element<T extends HTMLElement = HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing #${id}`);
  return value as T;
}

function nodeForEndpoint(
  endpoint: GraphEndpoint,
  byTicker: ReadonlyMap<string, GraphNode>,
): GraphNode | undefined {
  return typeof endpoint === "object" ? endpoint : byTicker.get(String(endpoint));
}

function renderNodeCard(node: GraphNode, degree: Record<string, number>): void {
  element("card-name").textContent = `${node.name} (${node.ticker})`;
  element("card-sector").textContent = [
    node.layer_name,
    node.segment,
    node.sector,
    node.industry,
  ].filter(Boolean).join(" · ");
  element("card-desc").textContent = node.description ?? "";

  const meta = element("card-meta");
  meta.replaceChildren();
  const detail = document.createElement("span");
  detail.textContent = `CIK ${node.id} · 度 ${degree[node.ticker] ?? 0}`;
  meta.append(detail);
  if (node.edgar) {
    meta.append(document.createElement("br"));
    const link = document.createElement("a");
    link.href = node.edgar;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "EDGAR 档案";
    meta.append(link);
  }
  element("card").hidden = false;
  element("link-card").hidden = true;
}

function renderLinkCard(link: GraphLink): void {
  const source = typeof link.source === "object" ? link.source.name : String(link.source);
  const target = typeof link.target === "object" ? link.target.name : String(link.target);
  element("link-title").textContent = `${source} ⟷ ${target}`;
  const description = element("link-desc");
  description.replaceChildren();
  const badge = document.createElement("span");
  badge.className = "badge";
  badge.textContent = link.type;
  description.append(badge, document.createTextNode(link.desc ?? ""));
  element("link-card").hidden = false;
  element("card").hidden = true;
}

export function mountGraph(
  container: HTMLElement,
  data: GraphPayload,
): ForceGraph3DInstance<GraphNode, GraphLink> {
  const degree = degreeByTicker(data);
  const byTicker = new Map(data.nodes.map((node) => [node.ticker, node] as const));
  const hidden = new Set<string>();
  const enabledTypes = new Set(["industry", "crossref"]);
  const colors = new Map<string, string>();
  let dimension: "sector" | "layer" = "sector";
  const groupOf = (node: GraphNode): string =>
    dimension === "sector"
      ? node.sector ?? "未分类"
      : node.layer_name ?? node.layer ?? "未分层";
  const endpointHidden = (endpoint: GraphEndpoint): boolean => {
    const node = nodeForEndpoint(endpoint, byTicker);
    return node ? hidden.has(groupOf(node)) : false;
  };
  const linkShown = (link: GraphLink): boolean =>
    enabledTypes.has(link.type) &&
    !endpointHidden(link.source) &&
    !endpointHidden(link.target);

  const TypedGraph = ThreeForceGraph as unknown as new (
    element: HTMLElement,
  ) => ForceGraph3DInstance<GraphNode, GraphLink>;
  const graph = new TypedGraph(container)
    .graphData(data)
    .nodeId("ticker")
    .nodeLabel((node) =>
      `${node.name} (${node.ticker})${node.layer_name ? ` · ${node.layer_name}` : ""}`,
    )
    .nodeVal((node) => 2 + Math.min(6, (degree[node.ticker] ?? 0) * 0.5))
    .nodeColor((node) => node.color ?? "#7f8dff")
    .linkColor((link) => (linkShown(link) ? linkColors[link.type] ?? "#556" : "#0a0e1a"))
    .linkVisibility(linkShown)
    .linkOpacity(0.55)
    .linkWidth((link) => (linkShown(link) ? Math.min(3, 0.6 + link.weight * 0.35) : 0))
    .backgroundColor("#0a0e1a")
    .showNavInfo(false);

  const applyFilters = (): void => {
    graph.nodeVisibility((node) => !hidden.has(groupOf(node)));
    graph.linkVisibility(linkShown);
    graph.d3Force("charge")?.distanceMax(300);
    graph.refresh();
  };

  const buildLegend = (): void => {
    const rows = element("legend-rows");
    rows.replaceChildren();
    const keys = [...new Set(data.nodes.map(groupOf))].sort();
    keys.forEach((key, index) => colors.set(key, palette[index % palette.length]));
    data.nodes.forEach((node) => {
      node.color = colors.get(groupOf(node));
    });
    graph.nodeColor((node) => node.color ?? "#7f8dff");

    keys.forEach((key) => {
      const row = document.createElement("label");
      row.className = "row";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = true;
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) hidden.delete(key);
        else hidden.add(key);
        applyFilters();
      });
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = colors.get(key) ?? palette[0];
      const name = document.createElement("span");
      name.textContent = key;
      const count = document.createElement("span");
      count.className = "row-count";
      count.textContent = String(data.nodes.filter((node) => groupOf(node) === key).length);
      row.append(checkbox, dot, name, count);
      rows.append(row);
    });
  };

  graph.onEngineStop(() => graph.zoomToFit(800, 80));
  graph.onNodeClick((node) => renderNodeCard(node, degree));
  graph.onNodeHover((node) => {
    container.style.cursor = node ? "pointer" : "default";
  });
  graph.onLinkClick(renderLinkCard);

  document.querySelectorAll<HTMLInputElement>('input[name="dim"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      dimension = radio.value === "layer" ? "layer" : "sector";
      hidden.clear();
      buildLegend();
      applyFilters();
    });
  });
  ["industry", "crossref", "coholding"].forEach((type) => {
    element<HTMLInputElement>(`ft-${type}`).addEventListener("change", (event) => {
      const checked = (event.currentTarget as HTMLInputElement).checked;
      if (checked) enabledTypes.add(type);
      else enabledTypes.delete(type);
      applyFilters();
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-close-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = button.closest<HTMLElement>(".panel");
      if (panel) panel.hidden = true;
    });
  });

  buildLegend();
  applyFilters();
  window.__graph = graph;
  window.__selectGraphNode = (ticker: string) => {
    const node = byTicker.get(ticker);
    if (node) renderNodeCard(node, degree);
  };
  return graph;
}

async function loadGraph(): Promise<void> {
  const status = element("graph-state");
  renderDataState(status, "loading", "正在读取公司关系图…");
  try {
    const payload = normalizeGraph(
      await apiGet<GraphPayload>("/api/v1/visualizations/graph"),
    );
    element("gen-time").textContent = payload.generated_at ?? "";
    mountGraph(element("graph"), payload);
    renderDataState(status, "ready", "");
  } catch (error) {
    renderDataState(
      status,
      "error",
      "公司关系图暂不可用。请确认可视化数据已生成。",
      () => void loadGraph(),
    );
    console.error(error);
  }
}

declare global {
  interface Window {
    __graph?: ForceGraph3DInstance<GraphNode, GraphLink>;
    __selectGraphNode?: (ticker: string) => void;
  }
}

if (document.querySelector("[data-graph-app]")) {
  void loadGraph();
}
