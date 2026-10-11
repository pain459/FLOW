"""Explicit local-stack browser acceptance; native Toolkit performs the fault."""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("WORKBENCH_UI_TEST") != "true",
    reason="Opt in to local-stack Chromium acceptance",
)


async def wait_for(predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(1)
    raise AssertionError("Bounded browser acceptance deadline exceeded")


async def test_workbench_catalog_history_and_disabled_scenario():
    from playwright.async_api import async_playwright, expect

    evidence = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
    evidence.mkdir(exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.goto("http://chaos-workbench:8090/")
        await expect(page.locator("h1")).to_have_text("Chaos Workbench")
        await expect(page.locator(".scenario")).to_have_count(8)
        await expect(page.locator("#gateway-status")).to_have_text("HEALTHY")
        await page.locator('[data-scenario="006-cpu-pressure"]').click()
        await expect(page.locator("#run")).to_be_disabled()
        await expect(page.locator("#scenario-note")).to_contain_text("Unavailable")
        await page.locator("#history-body button").first.click()
        await expect(page.locator("#report-panel")).to_be_visible()
        await expect(page.locator("#report-artifacts a").first).to_be_visible()
        await page.screenshot(path=str(evidence / "workbench-overview.png"), full_page=True)
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.screenshot(path=str(evidence / "workbench-mobile.png"), full_page=True)
        assert not errors, errors
        await browser.close()


async def test_idle_fault_preflight_displays_actionable_load_requirement():
    from playwright.async_api import async_playwright, expect

    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        state = (await client.get("http://locust:8089/stats/requests")).json()["state"]
        assert state in {"ready", "stopped"}, "This check requires idle Locust"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://chaos-workbench:8090/")
        await expect(page.locator("#load-guidance")).to_contain_text("8089")
        await expect(page.locator("#run")).to_be_disabled()
        await page.locator("#preflight").click()
        await expect(page.locator("#job-status")).to_have_text("FAILED", timeout=30000)
        await expect(page.locator("#job-output")).to_contain_text("LOAD_NOT_ACTIVE")
        await expect(page.locator("#job-output")).to_contain_text("Start a bounded")
        await page.locator("#refresh").click()
        await page.locator("#history-body button").first.click()
        await expect(page.locator("#report-summary")).to_contain_text("active steady HTTP load")
        await browser.close()


@pytest.mark.skipif(
    os.getenv("WORKBENCH_EXTERNAL_LOAD_TEST") != "true",
    reason="Requires explicit bounded existing workload",
)
async def test_browser_preserves_existing_load_during_worker_fault():
    from playwright.async_api import async_playwright, expect

    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:

        async def ready():
            return (await client.get("http://chaos-workbench:8090/api/status")).json()["workload"][
                "ready"
            ]

        await wait_for(ready, 90)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page()
            await page.goto("http://chaos-workbench:8090/")
            await expect(page.locator("#run")).to_be_enabled()
            await page.locator("#run").click()
            await page.locator("#confirm-form button[type=submit]").click()
            await expect(page.locator("#job-status")).to_have_text("RUNNING")
            await expect(page.locator("#job-status")).to_have_text("COMPLETED", timeout=210000)
            await expect(page.locator("#job-output")).to_contain_text('"result": "PASS"')
            latest = (await client.get("http://chaos-workbench:8090/api/runs")).json()["items"][0]
            report = (
                await client.get("http://chaos-workbench:8090/api/runs/" + latest["run_id"])
            ).json()
            assert report["summary"]["restoration"] == "RESTORED"
            assert report["summary"]["integrity"]["after"] == "PASS"
            assert report["summary"]["load"]["after_state"] == "RUNNING"
            path = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
            path.mkdir(exist_ok=True)
            (path / "gap-worker-run.json").write_text(json.dumps(report, indent=2))
            await page.screenshot(path=str(path / "gap-worker-recovery.png"), full_page=True)
            await browser.close()


@pytest.mark.skipif(
    os.getenv("WORKBENCH_FAULT_TEST") != "true",
    reason="Explicit worker-pause demonstration only",
)
async def test_browser_preflight_run_worker_pause_and_verified_recovery():
    from playwright.async_api import async_playwright, expect

    evidence = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
    evidence.mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        stats = (await client.get("http://locust:8089/stats/requests")).json()
        assert stats["state"] in {"ready", "stopped"}, "Acceptance must start with idle Locust"
        started = False
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 1100})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                response = await client.post(
                    "http://locust:8089/swarm",
                    data={"user_count": "5", "spawn_rate": "5", "host": "http://api:8080"},
                )
                assert response.status_code == 200, response.text
                started = True
                await page.goto("http://chaos-workbench:8090/")
                await expect(page.locator("#scenario-title")).to_have_text("worker pause")

                async def productive():
                    response = await client.get("http://locust:9101/metrics")
                    response.raise_for_status()
                    metrics = response.text
                    # Independent warmup plus a productive stable measured window.
                    observed_rps = [
                        float(line.rsplit(" ", 1)[-1])
                        for line in metrics.splitlines()
                        if line.startswith("load_measured_rps")
                    ]
                    return time.monotonic() - initial >= 48 and any(v > 0 for v in observed_rps)

                initial = time.monotonic()
                await wait_for(productive, 90)
                await page.locator("#preflight").click()
                await expect(page.locator("#job-status")).to_have_text("COMPLETED", timeout=90000)
                await expect(page.locator("#job-output")).to_contain_text(
                    "chaosloop-event-worker-1"
                )
                await expect(page.locator("#job-output")).to_contain_text("PREFLIGHT_PASS")
                await page.locator("#run").click()
                await expect(page.locator("#confirmation")).to_be_visible()
                await page.locator("#confirm-form button[type=submit]").click()
                await expect(page.locator("#job-status")).to_have_text("RUNNING")
                await page.screenshot(path=str(evidence / "workbench-running.png"), full_page=True)
                await expect(page.locator("#job-status")).to_have_text("COMPLETED", timeout=210000)
                await expect(page.locator("#job-output")).to_contain_text('"result": "PASS"')
                await page.locator("#refresh").click()
                await page.locator("#history-body button").first.click()
                await expect(page.locator("#report-summary")).to_contain_text('"result": "PASS"')
                await expect(page.locator("#report-verdicts")).to_contain_text(
                    "Restoration: RESTORED"
                )
                await page.screenshot(path=str(evidence / "workbench-recovery.png"), full_page=True)
                run_id = await page.locator("#report-title").inner_text()
                report = (await client.get("http://chaos-workbench:8090/api/runs/" + run_id)).json()
                assert report["summary"]["integrity"]["after"] == "PASS"
                assert report["summary"]["load"]["after_state"] == "RUNNING"
                (evidence / "workbench-run.json").write_text(json.dumps(report, indent=2))
                assert not errors, errors
            finally:
                if started:
                    (await client.get("http://locust:8089/stop")).raise_for_status()

                    async def stopped():
                        return (await client.get("http://locust:8089/stats/requests")).json()[
                            "state"
                        ] == "stopped"

                    await wait_for(stopped, 90)
                await browser.close()


@pytest.mark.skipif(os.getenv("WORKBENCH_FAULT_TEST") != "true", reason="Explicit abort test only")
async def test_browser_abort_active_fault_finalizes_and_releases():
    from playwright.async_api import async_playwright, expect

    evidence = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        initial = (await client.get("http://locust:8089/stats/requests")).json()
        assert initial["state"] in {"ready", "stopped"}
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 1100})
            try:
                response = await client.post(
                    "http://locust:8089/swarm",
                    data={"user_count": "5", "spawn_rate": "5", "host": "http://api:8080"},
                )
                assert response.status_code == 200, response.text
                await page.goto("http://chaos-workbench:8090/")
                await asyncio.sleep(48)
                await page.locator("#run").click()
                await page.locator("#confirm-form button[type=submit]").click()
                observed = {}

                async def actual_impact():
                    status = (await client.get("http://chaos-workbench:8090/api/status")).json()
                    active = status["active_experiment"]
                    if not active:
                        return False
                    identifier = active["run_id"]
                    response = await client.get(
                        f"http://chaos-workbench:8090/api/runs/{identifier}/artifacts/impact.json"
                    )
                    if response.status_code == 200 and response.json().get("observed"):
                        observed["run_id"] = identifier
                        return True
                    return False

                await wait_for(actual_impact, 90)
                await page.locator("#abort").click()
                await expect(page.locator("#job-status")).to_have_text("COMPLETED", timeout=150000)
                status = (await client.get("http://chaos-workbench:8090/api/status")).json()
                assert status["active_experiment"] is None
                identifier = observed["run_id"]
                report = (
                    await client.get("http://chaos-workbench:8090/api/runs/" + identifier)
                ).json()
                assert report["summary"]["result"] == "ABORTED"
                assert report["summary"]["restoration"] == "RESTORED"
                assert report["summary"]["integrity"]["after"] == "PASS"
                (evidence / "workbench-abort.json").write_text(json.dumps(report, indent=2))
                await page.screenshot(path=str(evidence / "workbench-abort.png"), full_page=True)
                await expect(page.locator("#run")).to_be_enabled()
            finally:
                (await client.get("http://locust:8089/stop")).raise_for_status()

                async def stopped():
                    return (await client.get("http://locust:8089/stats/requests")).json()[
                        "state"
                    ] == "stopped"

                await wait_for(stopped, 90)
                await browser.close()
