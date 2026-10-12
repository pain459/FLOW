"""Operator console against deployed shadow services; no fault or diagnostic execution."""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("INTELLIGENCE_UI_TEST") != "true", reason="Docker shadow-console test"
)
BASE = "http://investigation-ui:8092"


async def test_real_shadow_timeline_probability_display_and_mobile_layout():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(BASE + "/")
        await expect(page.locator("#health")).to_contain_text("HEALTHY", timeout=15000)
        await expect(page.locator("#sessions button").first).to_be_visible()
        # Choose a completed valid real session, without starting another inference.
        response = await page.request.get(BASE + "/api/v1/intelligence/investigations")
        valid = next(
            row for row in (await response.json())["items"] if row["state"] == "INCONCLUSIVE"
        )
        await page.locator("#sessions button").filter(has_text=valid["id"][:8]).click()
        await expect(page.locator("#details")).to_contain_text("executed: no", timeout=10000)
        assert await page.locator("meter").count() >= 8
        assert await page.evaluate("localStorage.length") == 0
        assert await page.locator("#token").get_attribute("type") == "password"
        await page.locator("details summary").first.click()
        await expect(page.locator("#details")).to_contain_text("source_quality")
        directory = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
        directory.mkdir(exist_ok=True)
        await page.screenshot(path=str(directory / "investigation-desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.screenshot(path=str(directory / "investigation-mobile.png"), full_page=True)
        assert not errors
        await browser.close()


async def test_browser_unauthorized_start_is_refused_without_creating_session():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(BASE + "/")
        await expect(page.locator("#dataset option").first).to_be_attached()
        await page.locator("#token").fill("invalid-local-token")
        await page.locator("#start").click()
        await expect(page.locator("#notice")).to_contain_text("401")
        assert await page.evaluate("localStorage.length") == 0
        await browser.close()


async def test_manual_first_response_form_and_unauthorized_query():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(BASE + "/")
        await expect(page.locator("#ask")).to_be_visible()
        await page.locator("#token").fill("invalid-local-token")
        await page.locator("#error-excerpt").fill("HTTP 503 DATABASE_UNAVAILABLE")
        await page.locator("#ask").click()
        await expect(page.locator("#ask-notice")).to_contain_text("401")
        assert await page.evaluate("localStorage.length") == 0
        await browser.close()
