import importlib.util
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest


def module():
    assert importlib.util.find_spec("decision_engine.adapters.calls"), (
        "read-only call explorer missing"
    )
    from decision_engine.adapters import calls

    return calls


def row(**extra):
    now = datetime.now(timezone.utc)
    return {
        "event": "http_request",
        "service": "api",
        "record_schema": 1,
        "call_id": str(uuid4()),
        "request_id": "same-retry",
        "trace_id": "1" * 32,
        "started_at": (now - timedelta(milliseconds=50)).isoformat(),
        "completed_at": now.isoformat(),
        "method": "GET",
        "route": "/api/v1/accounts/{account_id}",
        "status_code": 404,
        "duration_ms": 50,
        "error_code": "ACCOUNT_NOT_FOUND",
        "client_kind": "unknown",
        **extra,
    }


def loki(rows):
    return {
        "status": "success",
        "data": {
            "result": [
                {
                    "values": [
                        [
                            str(int(datetime.fromisoformat(r["completed_at"]).timestamp() * 1e9)),
                            json.dumps(r),
                        ]
                        for r in rows
                    ]
                }
            ]
        },
    }


def test_call_projection_has_safe_fields_and_distinct_attempts():
    m = module()
    raw = row(body="password=secret", message="FAULT_TRUTH_CANARY restart DB")
    first = m.project_call(raw)
    second = m.project_call({**raw, "call_id": str(uuid4())})
    assert first.id != second.id and first.request_id == second.request_id
    assert first.outcome == "business_rejection"
    assert first.error_code == "ACCOUNT_NOT_FOUND"
    for forbidden in ("secret", "FAULT_TRUTH_CANARY", "restart", "body", "message"):
        assert forbidden not in first.model_dump_json()
    assert m.project_call({**raw, "route": "/FAULT_TRUTH_CANARY"}) is None
    assert m.project_call({**raw, "duration_ms": float("nan")}) is None
    assert m.project_call({**raw, "record_schema": 0}) is None


async def test_calls_are_paginated_and_never_contact_model():
    m = module()
    from decision_engine.models.calls import CallQuery

    rows = [row() for _ in range(3)]
    requested = []

    def transport(request):
        requested.append(request)
        assert request.method == "GET" and request.url.host == "loki"
        assert 'event="http_request"' in request.url.params["query"]
        return httpx.Response(200, json=loki(rows))

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        page = await m.list_calls(CallQuery(limit=2), client=client)
    assert len(page["items"]) == 2 and page["next_cursor"]
    assert page["quality"]["status"] == "AVAILABLE"
    assert len(requested) == 1


async def test_unavailable_inventory_is_unknown_not_empty_healthy():
    m = module()
    from decision_engine.models.calls import CallQuery

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as c:
        page = await m.list_calls(CallQuery(), client=c)
    assert page["items"] == []
    assert page["quality"]["status"] == "UNKNOWN"


async def test_call_detail_retains_hierarchy_and_only_exact_async_correlation():
    m = module()
    data = row(status_code=201, error_code="", method="POST", route="/api/v1/transfers")
    call_id, trace_id = data["call_id"], data["trace_id"]
    end = int(datetime.fromisoformat(data["completed_at"]).timestamp() * 1e9)
    spans = [
        {
            "spanId": "2" * 16,
            "name": "FAULT_TRUTH_CANARY",
            "startTimeUnixNano": str(end - 50_000_000),
            "endTimeUnixNano": str(end),
            "attributes": [
                {"key": "http.status_code", "value": {"intValue": "201"}},
                {"key": "pulsepay.call_id", "value": {"stringValue": call_id}},
            ],
        },
        {
            "spanId": "3" * 16,
            "parentSpanId": "2" * 16,
            "name": "SELECT password=secret",
            "startTimeUnixNano": str(end - 30_000_000),
            "endTimeUnixNano": str(end - 1_000_000),
            "attributes": [{"key": "db.system", "value": {"stringValue": "postgresql"}}],
        },
    ]
    payload = {
        "batches": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }

    def transport(request):
        if request.url.host == "tempo":
            assert request.url.path == "/api/traces/" + trace_id
            return httpx.Response(200, json=payload)
        query = request.url.params["query"]
        assert f'call_id="{call_id}"' in query
        records = (
            [data]
            if 'event="http_request"' in query
            else [
                {
                    **data,
                    "service": "event-worker",
                    "event": "event_processed",
                    "call_id": str(uuid4()),
                },
                {**data, "service": "outbox-relay", "event": "outbox_published"},
            ]
        )
        return httpx.Response(200, json=loki(records))

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as c:
        detail = await m.call_detail(call_id, client=c)
    assert detail["call"]["id"] == call_id
    assert len(detail["trace"]["spans"]) == 2
    assert detail["trace"]["spans"][1]["parent_id"] == "2" * 16
    assert detail["trace"]["spans"][1]["operation"] == "database"
    assert detail["trace"]["status"] == "AVAILABLE"
    assert len(detail["related_events"]) == 1
    assert detail["related_events"][0]["service"] == "outbox-relay"
    assert "FAULT_TRUTH_CANARY" not in json.dumps(detail)
    assert "secret" not in json.dumps(detail)


async def test_call_state_queries_historical_time_and_never_current_health_or_verifier():
    m = module()
    ended = datetime.now(timezone.utc) - timedelta(minutes=5)
    raw = row(
        completed_at=ended.isoformat(), started_at=(ended - timedelta(milliseconds=50)).isoformat()
    )
    selected = m.project_call(raw).model_dump(mode="json")
    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == "prometheus", "current health must not explain historical call"
        assert (
            float(request.url.params["time"])
            == datetime.fromisoformat(raw["completed_at"]).timestamp()
        )
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    detail = {
        "call": selected,
        "trace": {"status": "UNKNOWN", "spans": []},
        "logs": [],
        "related_events": [],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as c:
        state = await m.call_state(detail, client=c)
    assert state.observed_at == datetime.fromisoformat(raw["completed_at"])
    assert state.integrity.status == "UNKNOWN"
    assert state.database.reachable is None
    assert state.api.rps is None
    assert state.request_evidence[0].error_codes == ["ACCOUNT_NOT_FOUND"]
    assert "same-retry" not in state.model_dump_json()
    assert raw["call_id"] not in state.model_dump_json()
    assert "1" * 32 not in state.model_dump_json()
    assert calls


def test_call_query_rejects_injection_and_unbounded_scans():
    module()
    from decision_engine.models.calls import CallQuery

    for kwargs in (
        {"limit": 10000},
        {"lookback_seconds": 90000},
        {"cursor": "http://docker"},
        {"route": '" |~ .*'},
        {"outcome": "delete_database"},
    ):
        with pytest.raises(ValueError):
            CallQuery(**kwargs)


@pytest.mark.parametrize("gateway", [False, True])
@pytest.mark.parametrize(
    "params",
    [
        {"route": "/not-a-registered-route"},
        {"limit": "10000"},
        {"lookback_seconds": "-1"},
        {"command": "restart"},
    ],
)
async def test_http_call_queries_fail_closed_with_422(gateway, params):
    from decision_engine.api import evidence, main

    app = evidence.app if gateway else main.app
    prefix = "/api/v1/evidence" if gateway else "/api/v1/intelligence"
    # Invalid queries must be rejected before reading telemetry or the controller.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(prefix + "/calls", params=params)
    assert response.status_code == 422, response.text


def test_reanalysis_requires_explicit_boolean():
    from decision_engine.models.calls import Explain

    assert Explain(reanalyse=True).reanalyse is True
    for value in ("true", "false", 1, 0):
        with pytest.raises(ValueError):
            Explain(reanalyse=value)


async def test_filtered_or_legacy_records_do_not_hide_older_calls():
    m = module()
    from decision_engine.models.calls import CallQuery

    newer = [row(record_schema=0), row(record_schema=0), row(record_schema=0)]
    old = datetime.now(timezone.utc) - timedelta(seconds=1)
    wanted = row(
        error_code=None,
        completed_at=old.isoformat(),
        started_at=(old - timedelta(milliseconds=50)).isoformat(),
    )
    requests = []

    def transport(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json=loki(newer))
        return httpx.Response(200, json=loki([wanted]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as c:
        first = await m.list_calls(CallQuery(limit=2, outcome="http_rejection"), client=c)
        assert first["next_cursor"], "raw scan progress must survive rejected/legacy rows"
        second = await m.list_calls(
            CallQuery(limit=2, outcome="http_rejection", cursor=first["next_cursor"]), client=c
        )
    assert len(second["items"]) == 1
    assert "error_code!~" in requests[0].url.params["query"]


def test_shared_trace_contains_only_selected_call_branch():
    m = module()
    selected = m.project_call(row())
    start = int(selected.started_at.timestamp() * 1e9)
    own, other = "2" * 16, "3" * 16
    spans = []
    for sid, parent, call_id in (
        (own, "1" * 16, str(selected.id)),
        ("4" * 16, own, None),
        (other, "1" * 16, str(uuid4())),
        ("5" * 16, other, None),
    ):
        spans.append(
            {
                "spanId": sid,
                "parentSpanId": parent,
                "name": "SELECT",
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(start + 1000),
                "attributes": [{"key": "pulsepay.call_id", "value": {"stringValue": call_id}}]
                if call_id
                else [],
            }
        )
    payload = {
        "batches": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }
    timeline = m.timeline(payload, selected)
    assert {s["id"] for s in timeline["spans"]} == {own, "4" * 16}


def test_uncorrelated_trace_never_becomes_call_evidence():
    m = module()
    selected = m.project_call(row())
    start = int(selected.started_at.timestamp() * 1e9)
    payload = {
        "batches": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "spanId": "2" * 16,
                                "name": "SELECT",
                                "startTimeUnixNano": str(start),
                                "endTimeUnixNano": str(start + 1000),
                                "attributes": [],
                            }
                        ]
                    }
                ],
            }
        ]
    }
    timeline = m.timeline(payload, selected)
    assert timeline["status"] == "UNKNOWN" and timeline["spans"] == []


async def test_pagination_preserves_calls_with_same_log_timestamp():
    m = module()
    from decision_engine.models.calls import CallQuery

    rows = [row() for _ in range(3)]
    same_stamp = str(int(datetime.now(timezone.utc).timestamp() * 1e9))
    payload = {
        "status": "success",
        "data": {"result": [{"values": [[same_stamp, json.dumps(r)] for r in rows]}]},
    }
    found, cursor = [], None
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as c:
        for _ in range(4):
            page = await m.list_calls(CallQuery(limit=1, cursor=cursor), client=c)
            found.extend(r["id"] for r in page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break
    assert len(found) == 3 and set(found) == {r["call_id"] for r in rows}
