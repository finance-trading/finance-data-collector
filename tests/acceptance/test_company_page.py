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
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
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
    assert console_errors == []
    page.close()
