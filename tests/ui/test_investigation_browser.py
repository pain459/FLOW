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
        await page.get_by_role("tab", name="History", exact=True).click()
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
        await page.locator("#authorize").click()
        assert await page.locator("#token").get_attribute("type") == "password"
        await page.locator("#close-auth").click()
        await (
            page.locator("#details details summary")
            .filter(has_text="Observation and source freshness")
            .first.click()
        )
        await expect(page.locator("#details")).to_contain_text("source_quality")
        directory = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
        directory.mkdir(exist_ok=True)
        await page.screenshot(path=str(directory / "investigation-desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.screenshot(path=str(directory / "investigation-mobile.png"), full_page=True)
        assert not errors
        await browser.close()


async def test_browser_unauthorized_session_is_refused_without_creating_session():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(BASE + "/")
        await page.locator("#authorize").click()
        await page.locator("#token").fill("invalid-local-token")
        await page.locator("#sign-in").click()
        await expect(page.locator("#auth-notice")).to_contain_text("401")
        assert await page.evaluate("localStorage.length") == 0
        await browser.close()


async def test_calls_default_has_no_questionnaire_or_automatic_analysis():
    from playwright.async_api import async_playwright, expect

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        posts = []
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        await page.goto(BASE + "/")
        await expect(page.get_by_role("tab", name="Calls", exact=True)).to_be_visible()
        await page.locator("#refresh-calls").click()
        await page.get_by_role("tab", name="History", exact=True).click()
        await page.get_by_role("tab", name="Recorded replays", exact=True).click()
        await page.get_by_role("tab", name="Calls", exact=True).click()
        assert await page.locator("#error-excerpt").count() == 0
        assert posts == []
        assert await page.evaluate("localStorage.length") == 0
        await browser.close()


async def test_reopened_active_call_tracks_completion_without_inference():
    import json
    from uuid import uuid4
    from playwright.async_api import async_playwright, expect

    call_id, session_id = str(uuid4()), str(uuid4())
    ended, posts = False, []
    call = {
        "id": call_id,
        "status_code": 404,
        "duration_ms": 2,
        "outcome": "business_rejection",
        "client_kind": "unknown",
        "method": "GET",
        "route": "/api/v1/accounts/{account_id}",
        "started_at": "2026-10-12T07:00:00Z",
        "completed_at": "2026-10-12T07:00:01Z",
        "request_id": None,
        "trace_id": None,
        "error_code": "ACCOUNT_NOT_FOUND",
        "error_class": None,
    }

    async def fixture(route):
        path = route.request.url.split("/api/v1/intelligence", 1)[1].split("?", 1)[0]
        session = {
            "id": session_id,
            "state": "INCONCLUSIVE" if ended else "DECIDING",
            "ended_at": "2026-10-12T07:00:10Z" if ended else None,
        }
        if path == "/health":
            data = {"status": "HEALTHY", "model": {"status": "HEALTHY"}, "analysis_busy": not ended}
        elif path == "/auth/session":
            data = {"authorized": True}
        elif path == "/calls":
            data = {"items": [call], "next_cursor": None, "quality": {"status": "AVAILABLE"}}
        elif path == "/calls/" + call_id:
            data = {
                "call": call,
                "analysis": session,
                "trace": {"status": "UNKNOWN", "spans": []},
                "logs": [],
                "logs_status": "UNKNOWN",
                "related_events": [],
            }
        elif path.endswith("/timeline"):
            data = {"decisions": [], "tool_calls": [], "first_response": None}
        else:
            data = session
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("**/api/v1/intelligence/**", fixture)
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        await page.goto(BASE + "/")
        await expect(page.locator(".call-row")).to_be_visible()
        await page.locator(".call-row").click()
        await expect(page.locator("#analysis-status")).to_have_text("DECIDING")
        await expect(page.locator("#cancel-analysis")).to_be_visible()
        ended = True
        await expect(page.locator("#analysis-status")).to_have_text("SAVED", timeout=15000)
        assert posts == []
        await browser.close()
