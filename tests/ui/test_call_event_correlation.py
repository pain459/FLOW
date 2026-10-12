"""One synthetic HTTP transfer/replay proves exact attempt and async correlation."""

import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("INTELLIGENCE_UI_TEST") != "true", reason="Docker deployed-call integration"
)


async def test_transfer_replay_keeps_distinct_call_branches_and_event_effects():
    api, intelligence = "http://api:8080", "http://investigation-ui:8092/api/v1/intelligence"
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        accounts = await client.get(api + "/api/v1/dashboard/accounts", params={"limit": 100})
        accounts.raise_for_status()
        funded = [
            a
            for a in accounts.json()["items"]
            if a["status"] == "active" and 0 < int(a["balance_minor"]) < 2**63 - 1
        ]
        assert len(funded) >= 2, "supported seeded accounts required"
        source = funded[0]
        destination = next(a for a in funded[1:] if a["currency"] == source["currency"])
        payload = {
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount_minor": 1,
            "currency": source["currency"],
        }
        trace_id, request_id = uuid4().hex, str(uuid4())
        headers = {
            "Idempotency-Key": "call-correlation-" + str(uuid4()),
            "X-Request-ID": request_id,
            "traceparent": f"00-{trace_id}-{uuid4().hex[:16]}-01",
        }
        first = await client.post(api + "/api/v1/transfers", json=payload, headers=headers)
        second = await client.post(api + "/api/v1/transfers", json=payload, headers=headers)
        assert first.status_code == 201, first.text
        assert second.status_code == 200, second.text
        assert first.json()["id"] == second.json()["id"]
        first_id, second_id = first.headers["X-Call-ID"], second.headers["X-Call-ID"]
        assert first_id != second_id
        deadline, details = time.monotonic() + 40, None
        while time.monotonic() < deadline:
            # The fixed evidence reader admits one detail collection at a time.
            responses = [await client.get(intelligence + "/calls/" + uid)
                         for uid in (first_id, second_id)]
            if all(r.status_code == 200 for r in responses):
                details = [r.json() for r in responses]
                if all(d["trace"]["spans"] for d in details) and {
                    e["service"] for e in details[0]["related_events"]
                } >= {"outbox-relay", "event-worker"}:
                    break
            await asyncio.sleep(2)
        assert details and all(d["trace"]["spans"] for d in details)
        assert {e["service"] for e in details[0]["related_events"]} >= {
            "outbox-relay",
            "event-worker",
        }
        assert details[1]["related_events"] == []
        first_statuses = {
            s["http_status"] for s in details[0]["trace"]["spans"] if s["service"] == "api"
        }
        second_statuses = {
            s["http_status"] for s in details[1]["trace"]["spans"] if s["service"] == "api"
        }
        assert 201 in first_statuses and 200 not in first_statuses
        assert 200 in second_statuses and 201 not in second_statuses
        directory = Path(os.getenv("UI_EVIDENCE_DIRECTORY", "/evidence"))
        directory.mkdir(exist_ok=True)
        (directory / "transfer-call-correlation.json").write_text(
            json.dumps(
                {
                    "first_call_id": first_id,
                    "replay_call_id": second_id,
                    "first_http_status": first.status_code,
                    "replay_http_status": second.status_code,
                    "same_transfer": True,
                    "model_requests": 0,
                    "details": details,
                },
                indent=2,
            )
        )
