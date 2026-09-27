from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_graph_mount_is_a_layout_container_for_three_force_graph():
    html = (PROJECT_ROOT / "web" / "graph.html").read_text()

    assert '<div id="graph"></div>' in html
    assert '<canvas id="graph"></canvas>' not in html


def test_graph_fits_all_nodes_after_force_layout_stabilizes():
    html = (PROJECT_ROOT / "web" / "graph.html").read_text()

    assert "Graph.zoomToFit(800, 80)" in html


def test_graph_uses_unique_ticker_as_node_identity_for_clicks():
    html = (PROJECT_ROOT / "web" / "graph.html").read_text()

    assert '.nodeId("ticker")' in html


def test_graph_click_handler_uses_ticker_for_degree_lookup():
    html = (PROJECT_ROOT / "web" / "graph.html").read_text()

    assert "degree[node.ticker]" in html


def test_graph_exposes_hover_state_without_reusing_a_fixed_node_label():
    html = (PROJECT_ROOT / "web" / "graph.html").read_text()

    assert ".onNodeHover(node =>" in html
    assert 'nodeLabel(n => `${n.name} (${n.ticker})' in html


def test_index_is_the_research_directory_and_preserves_graph_navigation():
    html = (PROJECT_ROOT / "web" / "index.html").read_text()

    assert 'id="company-search"' in html
    assert 'id="company-directory"' in html
    assert 'id="directory-state"' in html
    assert 'href="graph.html"' in html
    assert 'src="index.js"' in html
    assert 'href="data/index.css"' in html


def test_index_client_uses_only_the_read_api():
    script = (PROJECT_ROOT / "web" / "index.js").read_text()

    assert '"/api/v1/companies"' in script
    assert 'company.html?ticker=' in script
    assert "method:" not in script
