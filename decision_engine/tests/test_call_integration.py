"""Actual controller/store API; external telemetry and model replaced by bounded fixtures."""

import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from decision_engine.api.main import app
from decision_engine.adapters.datasets import catalog, load
from decision_engine.models.live import LiveModelState, Evidence
from decision_engine.providers.mock_provider import MockProvider
from decision_engine.tests.test_integration import client as integration_client, headers, wait

# Reuse the Docker-isolated controller/store fixture without redefining its setup.
client = integration_client


class Calls:
    def __init__(self):
        self.uid = uuid4()
        self.reads = 0

    async def list(self, query):
        self.reads += 1
        return {
            "items": [{"id": str(self.uid)}],
            "next_cursor": None,
            "quality": {"status": "AVAILABLE"},
        }

    async def detail(self, uid):
        self.reads += 1
        if str(uid) != str(self.uid):
            raise LookupError("CALL_NOT_OBSERVED")
        return {"call": {"id": str(self.uid)}, "trace": {"status": "UNKNOWN", "spans": []}}

    async def state(self, uid):
        await self.detail(uid)
        state = load(catalog()[0]["id"])[0][0]
        state["observed_at"] = datetime.now(timezone.utc).isoformat()
        return LiveModelState(
            **state,
            request_evidence=[
                Evidence(
                    source="loki",
                    quality="HISTORICAL",
                    http_statuses=[404],
                    error_codes=["ACCOUNT_NOT_FOUND"],
                )
            ],
        )


class Counter(MockProvider):
    def __init__(self, delay=0):
        super().__init__(delay=delay)
        self.calls = 0

    async def decide(self, state, questions):
        self.calls += 1
        assert "FAULT_TRUTH_CANARY" not in str(state)
        assert "call_id" not in str(state)
        return await super().decide(state, questions)


@pytest.fixture
def backend(client):
    calls, provider = Calls(), Counter()
    app.state.controller.call_collector = calls
    app.state.controller.provider = provider
    return calls, provider


async def test_browsing_calls_trace_and_saved_history_has_zero_inference(client, backend):
    calls, provider = backend
    for path in ("/calls", f"/calls/{calls.uid}", "/calls?trace_id=" + "1" * 32, "/investigations"):
        response = await client.get("/api/v1/intelligence" + path)
        assert response.status_code == 200, response.text
    assert provider.calls == 0


async def test_click_once_duplicates_and_saved_result_reuse_do_not_infer_again(client, backend):
    calls, provider = backend
    path = f"/api/v1/intelligence/calls/{calls.uid}/explain"
    h = headers()
    replies = await asyncio.gather(*[client.post(path, json={}, headers=h) for _ in range(3)])
    assert all(r.status_code == 202 for r in replies)
    assert len({r.json()["id"] for r in replies}) == 1
    uid = replies[0].json()["id"]
    await wait(client, uid)
    assert provider.calls == 1
    cached = await client.post(path, json={}, headers=headers())
    assert cached.json()["id"] == uid and cached.json()["cached"] is True
    assert provider.calls == 1
    detail = (await client.get(f"/api/v1/intelligence/calls/{calls.uid}")).json()
    assert detail["analysis"]["id"] == uid
    timeline = (await client.get(f"/api/v1/intelligence/investigations/{uid}/timeline")).json()
    assert timeline["tool_calls"] == [] and len(timeline["decisions"]) == 1
    assert timeline["first_response"]["executed_actions"] == 0
    assert str(calls.uid) not in str(timeline["decisions"][0]["observation"])


async def test_only_explicit_reanalysis_creates_new_decision(client, backend):
    calls, provider = backend
    path = f"/api/v1/intelligence/calls/{calls.uid}/explain"
    first = await client.post(path, json={}, headers=headers())
    assert first.status_code == 202
    await wait(client, first.json()["id"])
    second = await client.post(path, json={"reanalyse": True}, headers=headers())
    assert second.status_code == 202 and second.json()["id"] != first.json()["id"]
    await wait(client, second.json()["id"])
    assert provider.calls == 2


async def test_other_call_is_busy_while_analysis_is_running(client, backend):
    calls, _ = backend
    provider = Counter(delay=0.3)
    app.state.controller.provider = provider
    first = await client.post(
        f"/api/v1/intelligence/calls/{calls.uid}/explain", json={}, headers=headers()
    )
    assert first.status_code == 202
    busy = await client.post(
        f"/api/v1/intelligence/calls/{uuid4()}/explain", json={}, headers=headers()
    )
    assert busy.status_code == 429
    await wait(client, first.json()["id"])
    assert provider.calls == 1


async def test_missing_call_unauthorized_request_and_unknown_flags_cannot_start_model(
    client, backend
):
    calls, provider = backend
    path = f"/api/v1/intelligence/calls/{calls.uid}/explain"
    assert (
        await client.post(path, json={}, headers={"Idempotency-Key": "unauthorized"})
    ).status_code == 401
    assert (
        await client.post(path, json={"command": "restart DB"}, headers=headers())
    ).status_code == 422
    assert (
        await client.post(
            f"/api/v1/intelligence/calls/{uuid4()}/explain", json={}, headers=headers()
        )
    ).status_code == 404
    assert provider.calls == 0


async def test_session_auth_once_http_only_and_csrf_fail_closed(client, backend):
    calls, _ = backend
    login = await client.post(
        "/api/v1/intelligence/auth/session",
        json={"token": os.environ["DECISION_API_TOKEN"]},
        headers={"Origin": "http://test", "X-Requested-With": "PulsePay"},
    )
    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert os.environ["DECISION_API_TOKEN"] not in cookie
    assert (await client.get("/api/v1/intelligence/auth/session")).json()["authorized"] is True
    path = f"/api/v1/intelligence/calls/{calls.uid}/explain"
    for unsafe in ({}, {"Origin": "http://evil", "X-Requested-With": "PulsePay"}):
        assert (
            await client.post(path, json={}, headers={**unsafe, "Idempotency-Key": str(uuid4())})
        ).status_code == 403
    accepted = await client.post(
        path,
        json={},
        headers={
            "Origin": "http://test",
            "X-Requested-With": "PulsePay",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert accepted.status_code == 202
    await wait(client, accepted.json()["id"])
    await client.post(
        "/api/v1/intelligence/auth/logout",
        headers={"Origin": "http://test", "X-Requested-With": "PulsePay"},
    )
    assert (await client.get("/api/v1/intelligence/auth/session")).json()["authorized"] is False


async def test_same_key_different_call_is_conflict(client, backend):
    calls, _ = backend
    h = headers()
    first = await client.post(f"/api/v1/intelligence/calls/{calls.uid}/explain", json={}, headers=h)
    assert first.status_code == 202
    await wait(client, first.json()["id"])
    collision = await client.post(
        f"/api/v1/intelligence/calls/{uuid4()}/explain", json={}, headers=h
    )
    assert collision.status_code == 409
