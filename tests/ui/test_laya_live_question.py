"""Real call selection and explicit CPU Laya request; browsing never starts inference."""

import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("INTELLIGENCE_UI_TEST") != "true", reason="Docker call-analysis e2e"
)
BASE = "http://investigation-ui:8092"


async def test_real_call_selection_and_explicit_laya_analysis_only_once():
    from playwright.async_api import async_playwright, expect

    request_id, trace_id = str(uuid4()), uuid4().hex
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        before = (await client.get(BASE + "/api/v1/intelligence/investigations?limit=100")).json()["items"]
        response = await client.get(
            "http://api:8080/api/v1/accounts/" + str(uuid4()),
            headers={"X-Request-ID": request_id, "traceparent": f"00-{trace_id}-{uuid4().hex[:16]}-01"},
        )
        assert response.status_code == 404 and response.json()["code"] == "ACCOUNT_NOT_FOUND"
        call_id = response.headers["X-Call-ID"]
        deadline, detail = time.monotonic() + 40, None
        while time.monotonic() < deadline:
            listing = await client.get(BASE + "/api/v1/intelligence/calls", params={"trace_id": trace_id})
            assert listing.status_code == 200, listing.text
            if any(row["id"] == call_id for row in listing.json()["items"]):
                found = await client.get(BASE + "/api/v1/intelligence/calls/" + call_id)
                assert found.status_code == 200, found.text
                detail = found.json()
                if detail["trace"]["spans"]:
                    break
            await asyncio.sleep(2)
        assert detail and detail["trace"]["spans"], "real trace evidence never arrived"
        assert detail["call"]["request_id"] == request_id
        assert detail["call"]["error_code"] == "ACCOUNT_NOT_FOUND"
        after = (await client.get(BASE + "/api/v1/intelligence/investigations?limit=100")).json()["items"]
        assert [r["id"] for r in after] == [r["id"] for r in before], "browsing started inference"

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, analyses = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: analyses.append(r.url) if r.method == "POST" and r.url.endswith("/explain") else None)
        await page.goto(BASE + "/")
        await expect(page.locator("#health")).to_contain_text("HEALTHY", timeout=15000)
        await page.locator(".trace-shortcut summary").click()
        await page.locator("#trace-id").fill(trace_id)
        await page.get_by_role("button", name="Find call", exact=True).click()
        await expect(page.locator("#call-details")).to_contain_text(call_id, timeout=15000)
        await expect(page.locator("#call-details")).to_contain_text("ACCOUNT_NOT_FOUND")
        await expect(page.locator("#trace-status")).to_contain_text("AVAILABLE")
        assert analyses == [], "selecting a call invoked Laya"
        assert await page.locator("#error-excerpt").count() == 0

        await page.locator("#authorize").click()
        await page.locator("#token").fill(os.environ["DECISION_API_TOKEN"])
        await page.locator("#sign-in").click()
        await expect(page.locator("#auth-dialog")).not_to_be_visible()
        await expect(page.locator("#authorize")).to_have_text("Sign out")
        assert await page.locator("#token").input_value() == ""
        cookies = await page.context.cookies()
        auth = next(c for c in cookies if c["name"] == "pulsepay_operator")
        assert auth["httpOnly"] and auth["sameSite"] == "Strict"
        assert os.environ["DECISION_API_TOKEN"] not in auth["value"]

        async with page.expect_response(lambda r: r.url.endswith(f"/calls/{call_id}/explain") and r.request.method == "POST") as pending:
            await page.locator("#explain").click()
        started = await pending.value
        assert started.status == 202, await started.text()
        uid = (await started.json())["id"]
        # History navigation must not strand the pending call or start more inference.
        await page.get_by_role("tab", name="History", exact=True).click()
        await page.get_by_role("tab", name="Calls", exact=True).click()
        await expect(page.locator("#answer")).to_contain_text("Possible reason:", timeout=45000)
        await expect(page.locator("#answer")).to_contain_text("ACCOUNT_NOT_FOUND")
        await expect(page.locator("#answer")).to_contain_text("No action executed")
        assert len(analyses) == 1
        timeline = (await page.request.get(BASE + f"/api/v1/intelligence/investigations/{uid}/timeline"))
        trace = await timeline.json()
        assert trace["tool_calls"] == [] and len(trace["decisions"]) == 1
        assert trace["decisions"][0]["validation_status"] == "VALID"
        assert trace["first_response"]["confirmed_cause"] is False
        observed = json.dumps(trace["decisions"][0]["observation"])
        for identifier in (request_id, trace_id, call_id):
            assert identifier not in observed
        quality = trace["decisions"][0]["policy_decision"]["input_quality"]
        assert quality["state_tokens_dropped"] == 0 and quality["truncated"] is False

        await expect(page.locator("#explain")).to_have_text("View saved analysis", timeout=10000)
        await page.locator("#explain").click()
        assert len(analyses) == 1
        await page.reload()
        await expect(page.locator("#authorize")).to_have_text("Sign out")
        await page.locator(".trace-shortcut summary").click()
        await page.locator("#trace-id").fill(trace_id)
        await page.get_by_role("button", name="Find call", exact=True).click()
        await expect(page.locator("#answer")).to_contain_text("Possible reason:", timeout=15000)
        assert len(analyses) == 1, "reopening a saved result invoked Laya"
        assert await page.evaluate("localStorage.length") == 0
        assert await page.evaluate("sessionStorage.length") == 0

        directory = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
        directory.mkdir(exist_ok=True)
        (directory / "call-analysis-e2e.json").write_text(json.dumps({
            "session_id": uid, "call_id": call_id, "real_http_status": response.status_code,
            "browser_analysis_requests": len(analyses), "browsing_inference_requests": 0,
            "call_detail": detail, "timeline": trace,
        }, indent=2))
        await page.screenshot(path=str(directory / "calls-desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.screenshot(path=str(directory / "calls-mobile.png"), full_page=True)
        assert errors == []
        await browser.close()
