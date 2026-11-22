from pathlib import Path

import httpx
from playwright.sync_api import expect

from fdc import catalog

FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


def test_company_page_has_quality_dashboard_mounts():
    html = (FRONTEND_ROOT / "company.html").read_text()

    assert 'id="company-name"' in html
    assert 'id="company-identity"' in html
    assert 'id="company-status"' in html
    assert 'id="quality-score"' in html
    assert 'id="quality-dimensions"' in html
    assert 'id="financial-strength"' in html
    assert 'id="quality-notes"' in html
    assert 'id="quality-provenance"' in html
    assert 'id="filings"' not in html
    assert 'id="evidence"' not in html
    assert 'id="full-text"' not in html


def test_company_page_loads_its_styles_and_deferred_script():
    html = (FRONTEND_ROOT / "company.html").read_text()

    assert 'href="/src/styles/company.css"' in html
    assert 'src="/src/pages/company.ts"' in html
    assert 'type="module"' in html
    assert 'data-nav href="index.html"' in html


def test_company_page_requests_only_quality_score():
    script = (FRONTEND_ROOT / "src" / "pages" / "company.ts").read_text()

    assert '"/api/v1/companies/"' in script
    assert "/quality-score" in script
    assert "/api/v1/filings/" not in script
    assert "/statements" not in script
    assert "/facts" not in script
    assert "/sections" not in script
    assert "/tables" not in script
    assert "/evidence/" not in script
    assert "method:" not in script


def test_read_app_serves_company_page_on_the_api_origin(live_server):
    response = httpx.get(f"{live_server}/company.html?ticker=MSFT")

    assert response.status_code == 200
    assert 'id="company-name"' in response.text


def test_research_home_search_opens_the_company_workspace(browser, live_server):
    total_companies = len(catalog.load_catalog().companies)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    console_errors = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )

    page.goto(live_server)
    page.wait_for_load_state("networkidle")

    expect(page.get_by_role("heading", name="The AI company list.")).to_be_visible()
    expect(page.locator("#company-total")).to_have_text(str(total_companies))
    expect(page.locator("#company-directory-body tr")).to_have_count(25)
    expect(page.locator("#directory-pagination")).to_contain_text(f"1–25 of {total_companies}")

    page.get_by_role("button", name="Next").click()
    page.wait_for_function("location.search.includes('page=2')")
    assert "page=2" in page.url
    expect(page.locator("#directory-pagination")).to_contain_text(f"26–50 of {total_companies}")

    page.locator("#company-search").fill("VRT")
    page.get_by_role("button", name="Open company").click()
    expect(page.locator("#company-directory-body")).to_contain_text("VRT")
    expect(page.locator("#company-directory-body a[href*='company.html']")).to_have_count(0)

    page.locator("#company-search").fill("msft")
    page.get_by_role("button", name="Open company").click()
    page.wait_for_load_state("networkidle")

    expect(page).to_have_url(f"{live_server}/company.html?ticker=MSFT")
    expect(page.locator("#company-name")).to_have_text("Microsoft Fixture Corporation")
    expect(page.locator("#company-identity")).to_contain_text("MSFT")
    expect(page.locator("#company-identity")).to_contain_text("Technology")
    expect(page.locator("#company-status")).to_have_text("Qualified")
    expect(page.locator("#quality-score-body")).to_contain_text("42.50")
    expect(page.locator("#quality-dimensions")).to_contain_text("Revenue growth")
    expect(page.locator("#filings")).to_have_count(0)
    expect(page.locator("#evidence")).to_have_count(0)
    assert console_errors == []
    page.close()


def test_company_graph_renders_and_keeps_ticker_identity(browser, live_server):
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    console_errors = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )

    page.goto(f"{live_server}/graph.html")
    page.wait_for_function("Boolean(window.__graph)")

    expect(page.locator("#graph canvas")).to_have_count(1)
    assert page.evaluate("window.__graph.graphData().nodes.length") == len(catalog.load_catalog().companies)

    page.locator("#ft-crossref").uncheck()
    expect(page.locator("#ft-crossref")).not_to_be_checked()

    page.evaluate("window.__selectGraphNode('VRT')")
    expect(page.locator("#card-name")).to_contain_text("VRT")
    first_name = page.locator("#card-name").text_content()
    page.evaluate("window.__selectGraphNode('NVDA')")
    expect(page.locator("#card-name")).to_contain_text("NVDA")
    assert page.locator("#card-name").text_content() != first_name
    assert console_errors == []
    page.close()


def test_ai_layers_modes_collapse_search_and_narrow_layout(browser, live_server):
    total_companies = len(catalog.load_catalog().companies)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    console_errors = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )

    page.goto(f"{live_server}/layers.html")
    expect(page.locator("#stats")).to_contain_text(f"{total_companies} companies")
    expect(page.locator("#view")).to_be_visible()

    page.get_by_role("button", name="Tree").click()
    expect(page.get_by_role("button", name="Tree")).to_have_class("mode active")
    page.get_by_role("button", name="Mermaid").click()
    expect(page.locator("#mermaid")).to_be_visible()
    expect(page.locator("#mermaid")).to_contain_text("graph LR")
    page.get_by_role("button", name="Columns").click()
    expect(page.locator("#view")).to_be_visible()

    first_layer = page.locator("[data-layer-id]").first
    layer_id = first_layer.get_attribute("data-layer-id")
    first_layer.click()
    expect(page.locator(f'[data-layer-id="{layer_id}"] text').first).to_contain_text("▸")

    first_segment = page.locator("[data-segment-id]").first
    segment_id = first_segment.get_attribute("data-segment-id")
    first_segment.click()
    expect(page.locator(f'[data-segment-id="{segment_id}"] text').first).to_contain_text("▸")

    page.locator("#search").fill("NVDA")
    page.evaluate("window.__selectLayerCompany('NVDA')")
    expect(page.locator("#card-name")).to_contain_text("NVDA")
    page.locator("#search").fill("")

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    expect(page.locator("#stats")).to_contain_text(f"{total_companies} companies")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert console_errors == []
    page.close()


def test_company_page_does_not_request_filing_resources(browser, live_server):
    filing_requests = []
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.on(
        "request",
        lambda request: filing_requests.append(request.url)
        if "/api/v1/filings" in request.url
        else None,
    )

    page.goto(f"{live_server}/company.html?ticker=MSFT")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#quality-score")).to_be_visible()
    assert filing_requests == []
    page.close()


def test_company_page_shows_an_explicit_no_score_state(browser, live_server):
    page = browser.new_page(viewport={"width": 1280, "height": 800})

    page.goto(f"{live_server}/company.html?ticker=UNKNOWN")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#company-name")).to_have_text("UNKNOWN")
    expect(page.locator("#company-status")).to_have_text("Unavailable")
    expect(page.locator("#quality-score-body")).to_contain_text(
        "No score record is available for this company."
    )
    expect(page.locator("#quality-score-body")).to_have_attribute("role", "status")
    page.close()
