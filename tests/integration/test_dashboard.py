from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
from sqlalchemy import text
from tests.integration.test_financial import pool, body, send


async def test_dashboard_observes_real_worker_heartbeats(lab):
    from shared.runtime import write_heartbeat
    from shared.config import Settings
    from apps.pulsepay.infrastructure.db import Database

    worker = Database(Settings(database_url=lab.worker_url))
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        state = {
            "status": "HEALTHY",
            "last_success_at": stamp,
            "last_failure_at": None,
            "reason": "PROGRESS_CHECK",
        }
        for name in ("outbox-relay", "event-worker"):
            await write_heartbeat(worker, name, state)
        data = (await lab.client.get("/health/dependencies")).json()
        for name in ("outbox-relay", "event-worker"):
            assert data["dependencies"][name]["status"] == "HEALTHY"
            assert data["dependencies"][name]["last_success_at"] == stamp
        state.update(status="UNHEALTHY", last_failure_at=stamp)
        await write_heartbeat(worker, "event-worker", state)
        data = (await lab.client.get("/health/dependencies")).json()
        assert data["dependencies"]["event-worker"]["status"] == "UNHEALTHY"
    finally:
        await worker.close()


async def test_dashboard_serves_same_origin_assets(lab):
    response = await lab.client.get("/")
    assert response.status_code == 200
    assert "PulsePay" in response.text
    assert "/ui/app.js" in response.text
    assert (await lab.client.get("/ui/styles.css")).status_code == 200


async def test_dashboard_snapshot_and_transfer_details(lab):
    ids = await pool(lab)
    transfer = (await send(lab, body(ids))).json()
    response = await lab.client.get("/api/v1/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["accounts"] == 4
    assert data["totals"]["balance_minor"] == data["totals"]["provisioned_minor"] == "400000"
    assert data["totals"]["transfers"] == data["totals"]["outbox_pending"] == 1
    assert len(data["activity"]) == 30
    assert sum(p["count"] for p in data["activity"]) == 1
    assert data["recent_transfers"][0]["amount_minor"] == "100"
    detail = (await lab.client.get("/api/v1/dashboard/transfers/" + transfer["id"])).json()
    assert detail["transfer"]["id"] == transfer["id"]
    assert sorted(e["signed_amount_minor"] for e in detail["ledger"]) == ["-100", "100"]
    assert detail["transfer"]["event_status"] == "PENDING_PUBLICATION"


async def test_dashboard_empty_pagination_search_and_history(lab):
    empty = (await lab.client.get("/api/v1/dashboard")).json()
    assert empty["totals"]["accounts"] == 0
    assert empty["recent_transfers"] == []
    ids = await pool(lab)
    first = (await lab.client.get("/api/v1/dashboard/accounts?limit=2")).json()
    second = (
        await lab.client.get(
            "/api/v1/dashboard/accounts", params={"limit": 2, "cursor": first["next_cursor"]}
        )
    ).json()
    assert len({a["id"] for a in first["items"] + second["items"]}) == 4
    assert second["next_cursor"] is None
    ref = first["items"][0]["external_ref"]
    match = (await lab.client.get("/api/v1/dashboard/accounts", params={"search": ref})).json()
    assert any(a["external_ref"] == ref for a in match["items"])
    assert (await lab.client.get("/api/v1/dashboard/accounts", params={"search": "%"})).json()[
        "items"
    ] == []
    assert (await lab.client.get("/api/v1/dashboard/accounts?cursor=bad")).status_code == 422
    assert (await lab.client.get("/api/v1/dashboard/accounts?limit=101")).status_code == 422
    await send(lab, body(ids))
    history = (await lab.client.get("/api/v1/dashboard/accounts/" + ids[0] + "/ledger")).json()
    assert all(isinstance(e["signed_amount_minor"], str) for e in history["items"])
    assert (await lab.client.get("/api/v1/dashboard/transfers/" + str(uuid4()))).status_code == 404


async def test_dashboard_retains_bigint_precision(lab):
    created = (
        await lab.client.post(
            "/api/v1/accounts", json={"external_ref": "bigint-ui", "currency": "INR"}
        )
    ).json()
    amount = 9007199254740993
    run = uuid4()
    async with lab.admin.begin() as c:
        await c.execute(
            text("UPDATE accounts SET balance_minor=:amount WHERE id=:id"),
            {"amount": amount, "id": created["id"]},
        )
        await c.execute(
            text(
                "INSERT INTO seed_runs(id,version,account_count,balance_per_account,currency,issued_minor) VALUES(:id,'bigint-ui',1,:amount,'INR',:amount)"
            ),
            {"id": run, "amount": amount},
        )
        await c.execute(
            text(
                "INSERT INTO ledger_entries(id,account_id,seed_run_id,entry_kind,signed_amount_minor,currency) VALUES(:id,:account,:run,'provisioning',:amount,'INR')"
            ),
            {"id": uuid4(), "account": created["id"], "run": run, "amount": amount},
        )
    data = (await lab.client.get("/api/v1/dashboard")).json()
    assert data["totals"]["balance_minor"] == str(amount)
    account = (await lab.client.get("/api/v1/dashboard/accounts")).json()["items"][0]
    assert account["balance_minor"] == str(amount)
    detail = (await lab.client.get("/api/v1/dashboard/accounts/" + created["id"])).json()
    assert detail["balance_minor"] == str(amount)
    ledger = (
        await lab.client.get("/api/v1/dashboard/accounts/" + created["id"] + "/ledger")
    ).json()["items"][0]
    assert ledger["signed_amount_minor"] == str(amount)
    from verifier.main import reconcile

    assert (await reconcile(lab.verifier_url))["status"] == "PASS"


async def test_dashboard_optional_signals_never_invent_healthy_evidence(lab, monkeypatch):
    import apps.pulsepay.application.dashboard_service as service

    async def unavailable(url):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(service, "fetch_json", unavailable)
    signals = (await lab.client.get("/api/v1/dashboard/signals")).json()
    assert signals["verification"]["status"] == "UNKNOWN"
    assert signals["verification"]["report"] is None

    async def stale(url):
        return {
            "status": "PASS",
            "finished_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
            "checks": [],
        }

    monkeypatch.setattr(service, "fetch_json", stale)
    stale_signals = (await lab.client.get("/api/v1/dashboard/signals")).json()
    assert stale_signals["verification"]["status"] == "UNKNOWN"
    assert stale_signals["verification"]["reason"] == "STALE_REPORT"
    assert stale_signals["verification"]["report"] is None

    async def malformed(url):
        return {
            "status": "HEALTHY",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "reason": {"invalid": True},
            "last_success_at": "invalid",
        }

    monkeypatch.setattr(service, "fetch_json", malformed)
    response = await lab.client.get("/api/v1/dashboard/signals")
    assert response.status_code == 200
    assert response.json()["activity"]["status"] == "UNKNOWN"


async def test_dashboard_rejects_contradictory_independent_reports(lab, monkeypatch):
    import apps.pulsepay.application.dashboard_service as service

    for check_status, violations in [("FAIL", 1), ("PASS", 1), ("UNKNOWN", None)]:

        async def contradictory(url):
            return {
                "status": "PASS",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "checks": [
                    {
                        "name": "integrity",
                        "status": check_status,
                        "inspected_records": 1,
                        "violations": violations,
                        "details": [],
                    }
                ],
            }

        monkeypatch.setattr(service, "fetch_json", contradictory)
        data = (await lab.client.get("/api/v1/dashboard/signals")).json()
        assert data["verification"]["status"] == "UNKNOWN"
        assert data["verification"]["report"] is None

    async def unknown(url):
        return {
            "status": "UNKNOWN",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "checks": [
                {
                    "name": "database",
                    "status": "UNKNOWN",
                    "inspected_records": None,
                    "violations": None,
                    "details": ["Data unavailable"],
                }
            ],
        }

    monkeypatch.setattr(service, "fetch_json", unknown)
    data = (await lab.client.get("/api/v1/dashboard/signals")).json()
    assert data["verification"]["report"]["checks"][0]["violations"] is None
