from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def test_graph_mount_is_a_layout_container_for_three_force_graph():
    html = (FRONTEND_ROOT / "graph.html").read_text()

    assert '<main id="graph"' in html
    assert '<canvas id="graph"></canvas>' not in html


def test_graph_fits_all_nodes_after_force_layout_stabilizes():
    script = (FRONTEND_ROOT / "src" / "pages" / "graph.ts").read_text()

    assert "graph.zoomToFit(800, 80)" in script


def test_graph_uses_unique_ticker_as_node_identity_for_clicks():
    script = (FRONTEND_ROOT / "src" / "pages" / "graph.ts").read_text()

    assert '.nodeId("ticker")' in script


def test_graph_click_handler_uses_ticker_for_degree_lookup():
    script = (FRONTEND_ROOT / "src" / "pages" / "graph.ts").read_text()

    assert "degree[node.ticker]" in script


def test_graph_exposes_hover_state_without_reusing_a_fixed_node_label():
    script = (FRONTEND_ROOT / "src" / "pages" / "graph.ts").read_text()

    assert ".onNodeHover((node) =>" in script
    assert "`${node.name} (${node.ticker})" in script


def test_index_is_the_research_directory_and_preserves_graph_navigation():
    html = (FRONTEND_ROOT / "index.html").read_text()

    assert 'id="company-search"' in html
    assert 'id="company-directory"' in html
    assert 'id="directory-state"' in html
    assert 'id="directory-pagination"' in html
    assert 'id="layer-filter"' in html
    assert 'href="graph.html"' in html
    assert 'src="/src/pages/directory.ts"' in html
    assert 'href="/src/styles/index.css"' in html


def test_index_client_uses_only_the_read_api():
    script = (FRONTEND_ROOT / "src" / "pages" / "directory.ts").read_text()

    assert '"/api/v1/companies"' in script
    assert '"/api/v1/catalog/layers"' in script
    assert 'company.html?ticker=' in script
    assert "method:" not in script
