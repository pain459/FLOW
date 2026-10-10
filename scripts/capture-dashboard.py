"""Read-only Chromium capture of the deployed Docker lab; no financial writes."""

import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect


async def main():
    target = os.getenv("UI_CAPTURE_URL", "http://api:8080")
    evidence = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
    evidence.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1050})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto(target)
        await expect(page.locator("#metric-accounts")).not_to_have_text("—")
        await expect(page.locator("#verification-status")).to_have_text("PASS", timeout=30000)
        await page.screenshot(path=str(evidence / "live-overview-desktop.png"), full_page=True)
        for view in ("Accounts", "Transfers", "System"):
            await page.get_by_role("button", name=view, exact=True).click()
            if view == "Accounts":
                await expect(page.locator("#accounts-table tbody")).to_contain_text("seed:")
            if view == "Transfers":
                await expect(page.locator("#transfers-table tbody")).to_contain_text("Committed")
            await page.screenshot(
                path=str(evidence / f"live-{view.lower()}-desktop.png"), full_page=True
            )
        await page.get_by_role("button", name="Overview", exact=True).click()
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.screenshot(path=str(evidence / "live-overview-mobile.png"), full_page=True)
        signals = await (await page.request.get(target + "/api/v1/dashboard/signals")).json()
        health = await (await page.request.get(target + "/health/dependencies")).json()
        assert not errors, errors
        (evidence / "live-health.json").write_text(json.dumps(health, indent=2))
        (evidence / "live-signals.json").write_text(json.dumps(signals, indent=2))
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "browser_errors": errors,
                    "independent_verification": signals["verification"]["status"],
                    "screenshots": 5,
                }
            )
        )
        await browser.close()


asyncio.run(main())
