from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def test_index_is_the_research_directory_without_graph_navigation():
    html = (FRONTEND_ROOT / "companies.html").read_text()

    assert 'id="directory-search"' in html
    assert 'id="company-directory"' in html
    assert 'id="directory-state"' in html
    assert 'id="directory-pagination"' in html
    assert 'id="layer-filter"' in html
    assert 'href="graph.html"' not in html
    assert 'src="/src/pages/directory.ts"' in html
    assert 'href="/src/styles/index.css"' in html


def test_index_client_uses_only_the_read_api():
    script = (FRONTEND_ROOT / "src" / "pages" / "directory.ts").read_text()

    assert '"/api/v1/companies"' in script
    assert '"/api/v1/catalog/layers"' in script
    assert 'company.html?ticker=' in script
    assert "method:" not in script


def test_sources_and_workflow_docs_do_not_reference_legacy_web_data():
    source_paths = [
        *PROJECT_ROOT.joinpath("src").rglob("*.py"),
        *FRONTEND_ROOT.joinpath("src").rglob("*.ts"),
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "runbook.md",
    ]
    legacy_markers = ("web/data", "__FDC_DATA__", "mounts `web/`")
    offenders = []
    for path in source_paths:
        text = path.read_text()
        if any(marker in text for marker in legacy_markers):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []
