import asyncio
from pathlib import Path

import httpx
from playwright.sync_api import expect

from fdc.api import app

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_company_page_has_research_workspace_mounts():
    html = (WEB_ROOT / "company.html").read_text()

    assert 'id="filings"' in html
    assert 'id="income-statement"' in html
    assert 'id="balance-sheet"' in html
    assert 'id="cash-flow"' in html
    assert 'id="evidence"' in html
    assert '<main' in html
    assert '<table' in html


def test_company_page_loads_its_styles_and_deferred_script():
    html = (WEB_ROOT / "company.html").read_text()

    assert 'href="data/company.css"' in html
    assert 'src="company.js"' in html
    assert "defer" in html


def test_company_page_fetches_only_read_api_resources():
    script = (WEB_ROOT / "company.js").read_text()

    assert '"/api/v1/companies/"' in script
    assert '"/filings"' in script
    assert '"/api/v1/filings/"' in script
    assert '"/statements?statement_type="' in script
    assert '"/facts"' in script
    assert '"/sections/"' in script
    assert '"/tables"' in script
    assert '"/evidence/"' in script
    assert "method:" not in script


def test_company_page_preserves_explicit_data_states():
    script = (WEB_ROOT / "company.js").read_text()

    assert '"Not found"' in script
    assert '"Unavailable"' in script
    assert '"Unsupported"' in script
    assert '"Parse failed"' in script


def test_read_app_serves_company_page_on_the_api_origin():
    async def request_page() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/company.html?ticker=MSFT")

    response = asyncio.run(request_page())

    assert response.status_code == 200
    assert 'id="company-name"' in response.text


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
    page.locator('[data-accession="0000000000-24-000001"]').click()
    expect(page.locator("#selected-filing-date")).to_have_text("Aug 1, 2024")
    page.locator('[data-accession="0000000000-25-000002"]').click()
    expect(page.locator("#selected-filing-date")).to_have_text("Jan 25, 2025")

    page.locator("#balance-tab").click()
    expect(page.locator("#balance-sheet tbody")).to_contain_text("Total assets")
    page.locator("#cash-tab").click()
    expect(page.locator("#cash-flow tbody")).to_contain_text(
        "Operating cash flow"
    )

    page.locator("#fact-chart .evidence-button").first.click()
    expect(page.locator("#evidence-content")).to_contain_text("Content SHA-256")
    expect(page.locator("#evidence-content")).to_contain_text("Revenue 120")
    expect(page.locator("#evidence-content")).to_contain_text("us-gaap:Revenue")
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
