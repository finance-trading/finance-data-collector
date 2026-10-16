from pathlib import Path

import httpx
from playwright.sync_api import expect

from fdc import catalog

FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"


def test_company_page_has_research_workspace_mounts():
    html = (FRONTEND_ROOT / "company.html").read_text()

    assert 'id="filings"' in html
    assert 'id="income-statement"' in html
    assert 'id="balance-sheet"' in html
    assert 'id="cash-flow"' in html
    assert 'id="evidence"' in html
    assert '<main' in html
    assert '<table' in html


def test_company_page_loads_its_styles_and_deferred_script():
    html = (FRONTEND_ROOT / "company.html").read_text()

    assert 'href="/src/styles/company.css"' in html
    assert 'src="/src/pages/company.ts"' in html
    assert 'type="module"' in html
    assert 'data-nav href="index.html"' in html


def test_company_page_fetches_only_read_api_resources():
    script = (FRONTEND_ROOT / "src" / "pages" / "company.ts").read_text()

    assert '"/api/v1/companies/"' in script
    assert "/filings`" in script
    assert '"/api/v1/filings/"' in script
    assert "/statements`" in script
    assert "/facts`" in script
    assert "/sections/md_and_a`" in script
    assert "/tables`" in script
    assert "/evidence/" in script
    assert "method:" not in script


def test_company_page_preserves_explicit_data_states():
    script = (FRONTEND_ROOT / "src" / "pages" / "company.ts").read_text()

    assert '"Not found"' in script
    assert '"Unavailable"' in script
    assert '"Unsupported"' in script
    assert '"Parse failed"' in script


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
    expect(page.locator("#company-directory-body")).to_contain_text("Not ingested")
    expect(page.locator("#company-directory-body a[href*='company.html']")).to_have_count(0)

    page.locator("#company-search").fill("msft")
    page.get_by_role("button", name="Open company").click()
    page.wait_for_load_state("networkidle")

    expect(page).to_have_url(f"{live_server}/company.html?ticker=MSFT")
    expect(page.locator("#company-name")).to_have_text("Microsoft Fixture Corporation")
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


def test_company_page_end_to_end_uses_persisted_statement_names(browser, live_server):
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    console_errors = []
    evidence_requests = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on(
        "request",
        lambda request: evidence_requests.append(request.url)
        if "/evidence/" in request.url
        else None,
    )

    page.goto(f"{live_server}/company.html?ticker=MSFT")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#selected-accession")).to_have_text(
        "0000000000-25-000002"
    )
    expect(page.get_by_role("link", name="AI companies")).to_have_attribute(
        "href", "index.html"
    )
    page.locator('[data-accession="0000000000-24-000001"]').click()
    expect(page.locator("#selected-filing-date")).to_have_text("Aug 1, 2024")
    page.locator('[data-accession="0000000000-25-000002"]').click()
    expect(page.locator("#selected-filing-date")).to_have_text("Jan 25, 2025")

    page.locator("#income-tab").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator("#balance-tab")).to_be_focused()
    expect(page.locator("#balance-tab")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#balance-sheet tbody")).to_contain_text("Total assets")
    page.locator("#cash-tab").click()
    expect(page.locator("#cash-flow tbody")).to_contain_text(
        "Operating cash flow"
    )

    with page.expect_response(lambda response: "/evidence/" in response.url) as response_info:
        page.locator("#fact-chart .evidence-button").first.click()
    evidence_response = response_info.value
    evidence_payload = evidence_response.json()
    expect(page.locator("#evidence-content")).to_contain_text("Content SHA-256")
    expect(page.locator("#evidence-content")).to_contain_text(
        "Direct evidence endpoint response for 0000000000-25-000002"
    )
    expect(page.locator("#evidence-content")).not_to_contain_text("Revenue 120")
    expect(page.locator("#evidence-content")).to_contain_text("us-gaap:Revenue")
    assert evidence_response.status == 200
    assert evidence_payload["accession"] == "0000000000-25-000002"
    assert evidence_payload["excerpt"] == (
        "Direct evidence endpoint response for 0000000000-25-000002"
    )
    assert len(evidence_requests) == 1
    assert evidence_requests[0].startswith(
        f"{live_server}/api/v1/filings/0000000000-25-000002/evidence/"
    )
    assert evidence_requests[0].rsplit("/", 1)[-1]
    assert console_errors == []
    page.close()


def test_company_page_preserves_not_found_api_state(browser, live_server):
    page = browser.new_page(viewport={"width": 1280, "height": 800})

    page.goto(f"{live_server}/company.html?ticker=UNKNOWN")
    page.wait_for_load_state("networkidle")

    expect(page.locator("#company-status")).to_have_text("Not found")
    expect(page.locator("#company-identity")).to_contain_text(
        "Not found: unknown ticker UNKNOWN"
    )
    expect(page.locator("#company-identity")).not_to_contain_text("Unsupported")
    page.close()


def test_narrow_statement_keeps_period_visible(browser, live_server):
    page = browser.new_page(viewport={"width": 390, "height": 844})

    page.goto(f"{live_server}/company.html?ticker=MSFT")
    page.wait_for_load_state("networkidle")

    period = page.locator("#income-statement .line-period-mobile").first
    expect(period).to_be_visible()
    expect(period).to_contain_text("Period: Dec 31, 2024 / annual")
    expect(page.locator("#income-statement table")).to_have_attribute(
        "data-responsive-period", "stacked"
    )
    page.close()


def test_stale_evidence_failure_cannot_replace_new_filing_state(browser, live_server):
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.add_init_script(
        """
        (() => {
          const originalFetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const url = typeof input === "string" ? input : input.url;
            if (url.includes("/evidence/")) {
              return new Promise((_resolve, reject) => {
                window.__rejectEvidenceRequest = () => {
                  reject(new TypeError("delayed evidence failure"));
                };
              });
            }
            return originalFetch(input, init);
          };
        })();
        """
    )

    page.goto(f"{live_server}/company.html?ticker=MSFT")
    page.wait_for_load_state("networkidle")
    page.locator("#fact-chart .evidence-button").first.click()
    page.wait_for_function("typeof window.__rejectEvidenceRequest === 'function'")

    page.locator('[data-accession="0000000000-24-000001"]').click()
    expect(page.locator("#selected-accession")).to_have_text(
        "0000000000-24-000001"
    )
    page.evaluate("window.__rejectEvidenceRequest()")
    page.wait_for_timeout(100)

    expect(page.locator("#evidence-content")).to_contain_text(
        "Choose a source link beside a reported value"
    )
    expect(page.locator("#evidence-content")).not_to_contain_text(
        "Evidence could not be loaded"
    )
    page.close()
