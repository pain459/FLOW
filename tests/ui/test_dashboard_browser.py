"""Real Chromium/HTTP workflows confined to generated disposable databases."""

import asyncio
import os
from pathlib import Path
from datetime import datetime, timezone
import socket
import pytest
import pytest_asyncio
import uvicorn
from sqlalchemy import text
from tests.integration.test_financial import pool

pytestmark = pytest.mark.skipif(
    os.getenv("BROWSER_TESTS") != "true", reason="Run make ui-test for containerized Chromium"
)


@pytest_asyncio.fixture
async def ui(lab, monkeypatch, request):
    from playwright.async_api import async_playwright
    import apps.pulsepay.main as main
    from apps.pulsepay.application import dashboard_service
    from verifier.main import reconcile

    ids = await pool(lab)

    async def observed(url):
        if "report" in url:
            return await reconcile(lab.verifier_url)
        return {
            "status": "UNKNOWN",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "reason": "TEST_ACTIVITY_OFF",
        }

    monkeypatch.setattr(dashboard_service, "fetch_json", observed)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(
        uvicorn.Config(
            main.app,
            host="127.0.0.1",
            port=sock.getsockname()[1],
            lifespan="off",
            log_level="warning",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(100):
        if server.started:
            break
        if task.done():
            await task
        await asyncio.sleep(0.05)
    assert server.started
    evidence = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/tmp/pulsepay-ui-evidence"))
    evidence.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": 1440, "height": 1050}, reduced_motion="reduce"
        )
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            await page.goto(f"http://127.0.0.1:{sock.getsockname()[1]}/")
            yield page, ids, lab, errors
        finally:
            await page.screenshot(path=str(evidence / (request.node.name + ".png")), full_page=True)
            await browser.close()
            server.should_exit = True
            await asyncio.wait_for(task, 10)


async def test_overview_accounts_create_transfer_and_ledger(ui):
    from playwright.async_api import expect

    page, ids, lab, errors = ui
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    await expect(page.locator("#verification-status")).to_have_text("PASS")
    await page.get_by_role("button", name="Accounts", exact=True).click()
    await expect(page.locator("#accounts-table tbody tr")).to_have_count(4)
    await page.get_by_role("button", name="Create account", exact=True).click()
    await page.get_by_label("External reference").fill("browser-created")
    await page.get_by_role("button", name="Create account", exact=True).last.click()
    await expect(page.locator("#modal")).not_to_be_visible()
    await page.locator("#account-search").fill("browser-created")
    await expect(page.locator("#accounts-table tbody")).to_contain_text("browser-created")
    await page.get_by_role("button", name="browser-created", exact=True).click()
    await expect(page.locator("#modal")).to_contain_text("INR 0.00")
    await page.get_by_role("button", name="Close dialog", exact=True).click()
    await page.get_by_role("button", name="New transfer", exact=True).click()
    await page.get_by_label("Source account").fill(ids[0])
    await page.get_by_label("Destination account").fill(ids[1])
    await page.get_by_label("Amount in minor units").fill("100")
    await page.get_by_role("button", name="Commit transfer", exact=True).click()
    await expect(page.locator("#modal")).to_contain_text("Transfer committed")
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 1
        assert (
            await c.scalar(text("SELECT balance_minor FROM accounts WHERE id=:id"), {"id": ids[0]})
            == 99900
        )
    await page.get_by_role("button", name="View transfer", exact=True).click()
    await expect(page.locator("#modal")).to_contain_text("transfer_debit")
    await expect(page.locator("#modal")).to_contain_text("transfer_credit")
    assert not errors


async def test_exact_bigint_display_and_submission(ui):
    page, ids, lab, errors = ui
    result = await page.evaluate("""async () => {
      const {money, transferBody} = await import('/ui/api.js');
      return {display: money('9007199254740993'),
        body: transferBody({source_account_id: 'source', destination_account_id: 'destination',
          currency: 'INR', amount_minor: '9007199254740993'})};
    }""")
    assert result["display"] == "INR 9,00,71,99,25,47,409.93"
    assert '"amount_minor":9007199254740993' in result["body"]
    fallback = await page.evaluate("""async () => {
      Object.defineProperty(crypto, 'randomUUID', {value: undefined});
      const {uuid, request} = await import('/ui/api.js');
      return {id: uuid(), accounts: (await request('/api/v1/dashboard')).totals.accounts};
    }""")
    from uuid import UUID

    assert UUID(fallback["id"]).version == 4
    assert fallback["accounts"] == 4
    assert not errors


async def test_committed_response_loss_reloads_and_retries_same_intent(ui):
    from playwright.async_api import expect

    page, ids, lab, errors = ui
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    keys = []

    async def lose_response(route):
        keys.append(route.request.headers["idempotency-key"])
        response = await route.fetch()
        if len(keys) == 1:
            assert response.status == 201
            await route.fulfill(
                status=503,
                json={
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "Result not confirmed",
                    "request_id": "lost-response-test",
                },
            )
        else:
            await route.fulfill(response=response)

    await page.route("**/api/v1/transfers", lose_response)
    await page.get_by_role("button", name="New transfer", exact=True).click()
    await page.get_by_label("Source account").fill(ids[0])
    await page.get_by_label("Destination account").fill(ids[1])
    await page.get_by_label("Amount in minor units").fill("73")
    await page.get_by_role("button", name="Commit transfer", exact=True).click()
    await expect(page.locator("#modal")).to_contain_text("Result unconfirmed")
    await page.reload()
    await page.get_by_role("button", name="Resolve pending transfer", exact=True).click()
    await expect(page.get_by_label("Amount in minor units")).to_be_disabled()
    await page.get_by_role("button", name="Retry same transfer", exact=True).click()
    await expect(page.locator("#modal")).to_contain_text("Transfer confirmed")
    assert len(keys) == 2 and keys[0] == keys[1]
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 1
        assert (
            await c.scalar(text("SELECT balance_minor FROM accounts WHERE id=:id"), {"id": ids[0]})
            == 99927
        )
    assert not errors


async def test_storage_failure_blocks_transfer_submission(ui):
    from playwright.async_api import expect

    page, ids, lab, errors = ui
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    await page.evaluate(
        "() => { Storage.prototype.setItem = () => { throw new Error('disabled'); }; }"
    )
    await page.get_by_role("button", name="New transfer", exact=True).click()
    await page.get_by_label("Source account").fill(ids[0])
    await page.get_by_label("Destination account").fill(ids[1])
    await page.get_by_label("Amount in minor units").fill("73")
    await page.get_by_role("button", name="Commit transfer", exact=True).click()
    await expect(page.locator("#modal")).to_contain_text("Browser storage is unavailable")
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 0
    assert not errors


async def test_outage_keeps_stale_values_and_unknown_verification(ui):
    from playwright.async_api import expect

    page, ids, lab, errors = ui
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    await page.route(
        "**/api/v1/dashboard",
        lambda route: route.fulfill(
            status=503,
            json={
                "code": "DATABASE_UNAVAILABLE",
                "message": "Database unavailable",
                "request_id": "outage",
            },
        ),
    )
    await page.route(
        "**/api/v1/dashboard/signals",
        lambda route: route.fulfill(
            json={
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "verification": {
                    "status": "UNKNOWN",
                    "reason": "SOURCE_UNAVAILABLE",
                    "report": None,
                },
                "activity": {"status": "UNKNOWN", "reason": "SOURCE_UNAVAILABLE"},
            }
        ),
    )
    await page.get_by_role("button", name="Refresh data", exact=True).click()
    await expect(page.locator("#data-banner")).to_contain_text("Last successful snapshot")
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    await expect(page.locator("#verification-status")).to_have_text("UNKNOWN")
    assert not errors


async def test_mobile_layout_text_safety_and_keyboard_dialog(ui):
    from playwright.async_api import expect

    page, ids, lab, errors = ui
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    await page.evaluate("window.injected=false")
    async with lab.admin.begin() as c:
        await c.execute(
            text("UPDATE accounts SET external_ref=:ref WHERE id=:id"),
            {"id": ids[0], "ref": '<img src=x onerror="window.injected=true">'},
        )
    await page.get_by_role("button", name="Accounts", exact=True).click()
    await expect(page.locator("#accounts-table tbody")).to_contain_text("<img src=x")
    assert await page.evaluate("window.injected") is False
    await page.set_viewport_size({"width": 390, "height": 844})
    assert await page.evaluate("document.documentElement.scrollWidth<=window.innerWidth")
    await page.get_by_role("button", name="New transfer", exact=True).click()
    await expect(page.locator("#modal")).to_be_visible()
    await page.keyboard.press("Escape")
    await expect(page.locator("#modal")).not_to_be_visible()
    await expect(page.get_by_role("button", name="New transfer", exact=True)).to_be_focused()
    assert not errors


async def test_delayed_account_create_preserves_new_dialog(ui):
    from playwright.async_api import expect

    page, ids, lab, errors = ui
    await expect(page.locator("#metric-accounts")).to_have_text("4")
    committed = asyncio.Event()
    release = asyncio.Event()

    async def delay(route):
        response = await route.fetch()
        assert response.status == 201
        committed.set()
        await release.wait()
        await route.fulfill(response=response)

    await page.route("**/api/v1/accounts", delay)
    await page.get_by_role("button", name="Accounts", exact=True).click()
    await page.get_by_role("button", name="Create account", exact=True).click()
    await page.get_by_label("External reference").fill("delayed-account")
    await page.get_by_role("button", name="Create account", exact=True).last.click()
    await asyncio.wait_for(committed.wait(), 5)
    await page.keyboard.press("Escape")
    await page.get_by_role("button", name="New transfer", exact=True).click()
    await page.get_by_label("Amount in minor units").fill("42")
    release.set()
    await expect(page.locator("#toast")).to_contain_text("Created a zero-balance")
    await expect(page.get_by_label("Amount in minor units")).to_have_value("42")
    await expect(page.locator("#modal")).to_be_visible()
    assert not errors
