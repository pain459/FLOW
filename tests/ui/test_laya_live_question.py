"""Real manual query against deployed CPU Laya, logs/traces and current telemetry."""

import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("INTELLIGENCE_UI_TEST") != "true", reason="Docker manual-query e2e"
)
BASE = "http://investigation-ui:8092"


async def test_real_call_error_request_trace_and_laya_first_response():
    from playwright.async_api import async_playwright, expect

    request_id, trace_id = str(uuid4()), uuid4().hex
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        response = await client.get(
            "http://api:8080/api/v1/accounts/" + str(uuid4()),
            headers={
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-{uuid4().hex[:16]}-01",
            },
        )
        assert response.status_code == 404
        assert response.json()["code"] == "ACCOUNT_NOT_FOUND"
        assert response.headers["X-Request-ID"] == request_id
        deadline, projected = time.monotonic() + 35, None
        while time.monotonic() < deadline:
            result = await client.post(
                "http://evidence-reader:8093/api/v1/evidence/collect",
                json={"request_id": request_id},
            )
            assert result.status_code == 200, result.text
            projected = result.json()
            if any(e["source"] == "tempo" and e["spans"] for e in projected["request_evidence"]):
                break
            await asyncio.sleep(2)
        assert any(
            e["source"] == "loki" and e["matched_records"] for e in projected["request_evidence"]
        )
        assert any(e["source"] == "tempo" and e["spans"] for e in projected["request_evidence"])
        assert request_id not in json.dumps(projected)
        assert trace_id not in json.dumps(projected)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(BASE + "/")
        await expect(page.locator("#health")).to_contain_text("HEALTHY", timeout=15000)
        await page.locator("#token").fill(os.environ["DECISION_API_TOKEN"])
        await page.locator("#request-id").fill(request_id)
        await page.locator("#error-excerpt").fill(json.dumps({"code": response.json()["code"]}))
        async with page.expect_response(
            lambda r: r.url.endswith("/intelligence/ask") and r.request.method == "POST"
        ) as pending:
            await page.locator("#ask").click()
        started = await pending.value
        assert started.status == 202
        uid = (await started.json())["id"]
        # A completed old recording must not strand the active question button.
        listing = await page.request.get(BASE + "/api/v1/intelligence/investigations")
        other = next(
            row for row in (await listing.json())["items"] if row["ended_at"] and row["id"] != uid
        )
        await expect(
            page.locator("#sessions button").filter(has_text=other["id"][:8])
        ).to_be_visible()
        await page.locator("#sessions button").filter(has_text=other["id"][:8]).click()
        await expect(page.locator("#ask")).to_be_enabled(timeout=45000)
        await page.locator("#sessions button").filter(has_text=uid[:8]).click()
        await expect(page.locator("#answer")).to_contain_text("Possible reason:", timeout=15000)
        await expect(page.locator("#answer")).to_contain_text("ACCOUNT_NOT_FOUND")
        await expect(page.locator("#answer")).to_contain_text("No action executed")
        assert await page.evaluate("localStorage.length") == 0
        result = await page.request.get(
            BASE + f"/api/v1/intelligence/investigations/{uid}/timeline"
        )
        timeline = await result.json()
        assert timeline["tool_calls"] == []
        assert len(timeline["decisions"]) == 1
        assert timeline["decisions"][0]["question_set_version"] == "first-response-v1"
        assert timeline["first_response"]["confirmed_cause"] is False
        assert timeline["first_response"]["executed_actions"] == 0
        assert request_id not in json.dumps(timeline)
        assert trace_id not in json.dumps(timeline)
        directory = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
        directory.mkdir(exist_ok=True)
        (directory / "manual-question-e2e.json").write_text(
            json.dumps(
                {
                    "session_id": uid,
                    "real_http_status": response.status_code,
                    "real_error_code": response.json()["code"],
                    "correlated_sources": projected["request_evidence"],
                    "timeline": timeline,
                },
                indent=2,
            )
        )
        await page.screenshot(path=str(directory / "manual-question-desktop.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        await page.screenshot(path=str(directory / "manual-question-mobile.png"), full_page=True)
        assert errors == []
        await browser.close()
