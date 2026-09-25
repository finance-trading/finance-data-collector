from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_graph_mount_is_a_layout_container_for_three_force_graph():
    html = (PROJECT_ROOT / "web" / "index.html").read_text()

    assert '<div id="graph"></div>' in html
    assert '<canvas id="graph"></canvas>' not in html


def test_graph_fits_all_nodes_after_force_layout_stabilizes():
    html = (PROJECT_ROOT / "web" / "index.html").read_text()

    assert "Graph.zoomToFit(800, 80)" in html


def test_graph_uses_unique_ticker_as_node_identity_for_clicks():
    html = (PROJECT_ROOT / "web" / "index.html").read_text()

    assert '.nodeId("ticker")' in html


def test_graph_click_handler_uses_ticker_for_degree_lookup():
    html = (PROJECT_ROOT / "web" / "index.html").read_text()

    assert "degree[node.ticker]" in html


def test_graph_exposes_hover_state_without_reusing_a_fixed_node_label():
    html = (PROJECT_ROOT / "web" / "index.html").read_text()

    assert ".onNodeHover(node =>" in html
    assert 'nodeLabel(n => `${n.name} (${n.ticker})' in html
