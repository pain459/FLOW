import asyncio
import os
from uuid import uuid4

import httpx
import asyncpg
import pytest

from decision_engine.api.main import app
from decision_engine.adapters.datasets import catalog
from decision_engine.controller.store import Store
from decision_engine.providers.mock_provider import MockProvider


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        app.state.controller.provider = MockProvider()
        app.state.controller.allow_fixture = True
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


def headers(key=None):
    return {
        "Authorization": "Bearer " + os.environ["DECISION_API_TOKEN"],
        "Idempotency-Key": key or str(uuid4()),
    }


async def wait(c, uid):
    for _ in range(50):
        row = (await c.get(f"/api/v1/intelligence/investigations/{uid}")).json()
        if row["ended_at"]:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError("session did not terminate")


async def test_post_authorization_and_readonly_refusal(client):
    body = {"dataset_ref": catalog()[0]["id"], "budget": {"decisions": 1}}
    assert (
        await client.post(
            "/api/v1/intelligence/replays", json=body, headers={"Idempotency-Key": "unauthorized"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/intelligence/replays", json={**body, "mode": "readonly"}, headers=headers()
        )
    ).status_code == 423


async def test_durable_idempotent_shadow_trace_and_no_tools(client):
    h = headers()
    body = {"dataset_ref": catalog()[0]["id"], "budget": {"decisions": 2}}
    first = await client.post("/api/v1/intelligence/replays", json=body, headers=h)
    assert first.status_code == 202, first.text
    uid = first.json()["id"]
    assert (await client.post("/api/v1/intelligence/replays", json=body, headers=h)).json()[
        "id"
    ] == uid
    assert (
        await client.post(
            "/api/v1/intelligence/replays", json={**body, "budget": {"decisions": 3}}, headers=h
        )
    ).status_code == 409
    row = await wait(client, uid)
    assert row["state"] == "INCONCLUSIVE"
    trace = (await client.get(f"/api/v1/intelligence/investigations/{uid}/timeline")).json()
    assert len(trace["decisions"]) == 2
    assert all(d["policy_decision"]["execute"] is False for d in trace["decisions"])
    assert all("chaos-" not in str(d["observation"]) for d in trace["decisions"])
    async with app.state.controller.store.pool.acquire() as c:
        assert (
            await c.fetchval(
                "SELECT count(*) FROM decision_intel.tool_calls WHERE session_id=$1",
                uuid4().__class__(uid),
            )
            == 0
        )


async def test_provider_failure_escalates_and_cancel_is_bounded(client):
    app.state.controller.provider = MockProvider(fail=True)
    body = {"dataset_ref": catalog()[0]["id"], "budget": {"decisions": 2}}
    uid = (await client.post("/api/v1/intelligence/replays", json=body, headers=headers())).json()[
        "id"
    ]
    assert (await wait(client, uid))["state"] == "ESCALATED"
    app.state.controller.provider = MockProvider(delay=2)
    uid = (await client.post("/api/v1/intelligence/replays", json=body, headers=headers())).json()[
        "id"
    ]
    await asyncio.sleep(0.05)
    result = await client.post(
        f"/api/v1/intelligence/investigations/{uid}/cancel", headers=headers()
    )
    assert result.json()["state"] == "CANCELLED"


async def test_decision_role_cannot_read_truth_or_mutate_finance():
    s = await Store.open(os.environ["DECISION_DATABASE_URL"])
    async with s.pool.acquire() as c:
        for table in ("accounts", "transfers", "ledger_entries", "outbox_events"):
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "SELECT"):
                assert not await c.fetchval(
                    "SELECT has_table_privilege(current_user,$1,$2)", table, privilege
                )
        assert not await c.fetchval(
            "SELECT has_schema_privilege(current_user,'decision_evaluation','USAGE')"
        )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.execute("UPDATE public.accounts SET balance_minor=balance_minor WHERE false")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await c.execute("SELECT * FROM decision_evaluation.evaluation_items LIMIT 1")
    await s.pool.close()


async def test_streamed_oversized_body_is_bounded_and_redacted(client):
    async def chunks():
        yield b'{"FAULT_TRUTH_CANARY":"'
        yield b"x" * 20000
        yield b'"}'

    r = await client.post("/api/v1/intelligence/replays", content=chunks(), headers=headers())
    assert r.status_code == 413
    assert "FAULT_TRUTH_CANARY" not in r.text


@pytest.mark.parametrize("failure", ["oom", "illegal_tool", "canary", "provider_metadata"])
async def test_invalid_or_failed_provider_never_executes_or_leaks(client, failure):
    class InvalidProvider(MockProvider):
        async def decide(self, state, questions):
            if failure == "oom":
                raise MemoryError("FAULT_TRUTH_CANARY")
            result = await super().decide(state, questions)
            if failure == "illegal_tool":
                result["raw_answers"]["next_diagnostic_tool"]["choice"] = "restart_database"
            elif failure == "provider_metadata":
                result["provider_version"] = "FAULT_TRUTH_CANARY"
            else:
                result["raw_answers"]["incident_severity"]["noul"] = "FAULT_TRUTH_CANARY"
            return result

    app.state.controller.provider = InvalidProvider()
    uid = (
        await client.post(
            "/api/v1/intelligence/replays",
            headers=headers(),
            json={"dataset_ref": catalog()[0]["id"]},
        )
    ).json()["id"]
    row = await wait(client, uid)
    assert row["state"] == "ESCALATED"
    trace = (await client.get(f"/api/v1/intelligence/investigations/{uid}/timeline")).json()
    assert "FAULT_TRUTH_CANARY" not in str(trace)
    assert trace["decisions"][0]["policy_decision"]["execute"] is False
    from pathlib import Path

    directory = Path("/reports") / uid
    for path in directory.glob("*"):
        assert "FAULT_TRUTH_CANARY" not in path.read_text()


async def test_concurrent_session_cap_cancel_and_timeout(client):
    app.state.controller.provider = MockProvider(delay=2)
    body = {"dataset_ref": catalog()[0]["id"], "budget": {"inference_seconds": 1, "decisions": 1}}
    starts = await asyncio.gather(
        *[
            client.post("/api/v1/intelligence/replays", json=body, headers=headers())
            for _ in range(3)
        ]
    )
    assert sorted(r.status_code for r in starts) == [202, 202, 429]
    ids = [r.json()["id"] for r in starts if r.status_code == 202]
    for uid in ids:
        await client.post(f"/api/v1/intelligence/investigations/{uid}/cancel", headers=headers())
    for uid in ids:
        assert (await wait(client, uid))["state"] == "CANCELLED"


async def test_fresh_test_database_has_no_financial_records():
    s = await Store.open(os.environ["DECISION_DATABASE_URL"])
    assert s.pool.get_max_size() == 2
    async with s.pool.acquire() as c:
        assert await c.fetchval("SELECT current_database()") == "pulsepay_decision_test"
        assert not await c.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
    await s.pool.close()


async def test_repeated_cancel_preserves_sealed_final_evidence(client, monkeypatch):
    from pathlib import Path
    from decision_engine.evaluation import export

    app.state.controller.provider = MockProvider(delay=2)
    entered, release = asyncio.Event(), asyncio.Event()
    original = export.export_session

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(export, "export_session", delayed)
    uid = (
        await client.post(
            "/api/v1/intelligence/replays",
            json={"dataset_ref": catalog()[0]["id"]},
            headers=headers(),
        )
    ).json()["id"]
    await asyncio.sleep(0.02)
    first = asyncio.create_task(
        client.post(f"/api/v1/intelligence/investigations/{uid}/cancel", headers=headers())
    )
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(
        client.post(f"/api/v1/intelligence/investigations/{uid}/cancel", headers=headers())
    )
    await asyncio.sleep(0.02)
    release.set()
    results = await asyncio.gather(first, second)
    assert all(r.json()["state"] == "CANCELLED" for r in results)
    assert (Path("/reports") / uid / "checksums.json").exists()
