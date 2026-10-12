import asyncio
import json
import logging
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from shared.logging import JsonFormatter


def request(headers=()):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/transfers",
            "headers": headers,
            "query_string": b"password=secret",
            "route": SimpleNamespace(path="/api/v1/transfers"),
            "pulsepay_trace_id": "1" * 32,
        }
    )


@pytest.mark.parametrize(
    "outcome,status", [("success", 201), ("rejected", 422), ("exception", 500), ("timeout", 503)]
)
async def test_each_http_outcome_has_one_complete_call_record(caplog, monkeypatch, outcome, status):
    from apps.pulsepay import main

    monkeypatch.setattr(main.config, "request_timeout_seconds", 0.01)
    req = request([(b"x-request-id", b"same-retry-id")])

    async def handle(r):
        if outcome == "exception":
            raise ValueError("password=secret FAULT_TRUTH_CANARY")
        if outcome == "timeout":
            await asyncio.sleep(1)
        if outcome == "rejected":
            r.scope["pulsepay_error_code"] = "INSUFFICIENT_FUNDS"
        return JSONResponse({"private": "account-value"}, status_code=status)

    with caplog.at_level(logging.INFO):
        response = await main.request_boundary(req, handle)
    rows = [r for r in caplog.records if getattr(r, "event", None) == "http_request"]
    assert len(rows) == 1
    row = rows[0]
    assert getattr(row, "call_id", None), "completion record needs a distinct call ID"
    assert UUID(row.call_id)
    assert row.method == "POST"
    assert row.route == "/api/v1/transfers"
    assert row.status_code == response.status_code == status
    assert row.duration_ms >= 0
    assert row.started_at.endswith("+00:00")
    assert response.headers["X-Call-ID"] == row.call_id
    if outcome == "rejected":
        assert row.error_code == "INSUFFICIENT_FUNDS"
    if outcome in ("exception", "timeout"):
        assert row.error_class == ("ValueError" if outcome == "exception" else "TimeoutError")
    assert "secret" not in row.getMessage()
    assert "FAULT_TRUTH_CANARY" not in row.getMessage()


async def test_same_request_id_retry_is_two_distinct_attempts(caplog):
    from apps.pulsepay.main import request_boundary

    async def handle(r):
        return JSONResponse({})

    with caplog.at_level(logging.INFO):
        first = await request_boundary(request([(b"x-request-id", b"same")]), handle)
        second = await request_boundary(request([(b"x-request-id", b"same")]), handle)
    assert first.headers.get("X-Call-ID"), "attempt identity header missing"
    assert first.headers["X-Call-ID"] != second.headers["X-Call-ID"]
    assert first.headers["X-Request-ID"] == second.headers["X-Request-ID"] == "same"


def test_formatter_retains_only_safe_call_fields():
    row = logging.LogRecord("api", logging.INFO, "", 0, "http_request", (), None)
    for key, value in {
        "call_id": "00000000-0000-0000-0000-000000000001",
        "method": "GET",
        "route": "/api/v1/accounts/{identifier}/balance",
        "status_code": 404,
        "duration_ms": 12.3,
        "started_at": "2026-10-12T00:00:00+00:00",
        "error_code": "ACCOUNT_NOT_FOUND",
        "record_schema": 1,
        "body": "password=secret",
        "url": "http://db:secret@postgres/private",
    }.items():
        setattr(row, key, value)
    value = json.loads(JsonFormatter("api").format(row))
    assert value.get("call_id") == row.call_id
    assert value["status_code"] == 404
    assert value["record_schema"] == 1
    assert "body" not in value and "url" not in value
    assert "secret" not in json.dumps(value)


async def test_oversized_transfer_before_routing_retains_registered_template(caplog):
    from apps.pulsepay import main

    req = request([(b"content-length", b"16385")])
    req.scope.pop("route")

    async def handler(r):
        pytest.fail("oversized request must not reach handler")

    with caplog.at_level(logging.INFO):
        response = await main.request_boundary(req, handler)
    row = next(r for r in caplog.records if getattr(r, "event", None) == "http_request")
    assert response.status_code == 413
    assert row.route == "/api/v1/transfers"


async def test_server_trace_hook_tags_generated_attempt_before_middleware(caplog):
    from apps.pulsepay import main

    tagged = {}
    span = SimpleNamespace(
        get_span_context=lambda: SimpleNamespace(is_valid=True, trace_id=1),
        set_attribute=lambda key, value: tagged.update({key: value}),
    )
    req = request()
    main.capture_request_trace(span, req.scope)
    assert tagged.get("pulsepay.call_id"), "HTTP root must carry attempt identity"

    async def handler(r):
        return JSONResponse({})

    with caplog.at_level(logging.INFO):
        response = await main.request_boundary(req, handler)
    assert response.headers["X-Call-ID"] == tagged["pulsepay.call_id"]


async def test_nested_server_hook_reuses_middleware_attempt_identity():
    from apps.pulsepay import main

    tagged = {}
    span = SimpleNamespace(
        get_span_context=lambda: SimpleNamespace(is_valid=True, trace_id=1),
        set_attribute=lambda key, value: tagged.update({key: value}),
    )

    async def handler(req):
        # Instrumentation can be nested inside request-boundary middleware.
        main.capture_request_trace(span, req.scope)
        return JSONResponse({})

    response = await main.request_boundary(request(), handler)
    assert response.headers["X-Call-ID"] == tagged["pulsepay.call_id"]
