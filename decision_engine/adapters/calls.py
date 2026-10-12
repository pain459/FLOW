"""Call inventory and sanitized timelines from fixed, read-only telemetry APIs."""

import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from uuid import UUID

import httpx

from decision_engine.adapters.live_evidence import read
from decision_engine.models.calls import Call, CallQuery, ROUTES
from decision_engine.models.live import ERROR_CLASSES, ERROR_CODES, attributes

LOKI = "http://loki:3100"
LOGS_PATH = "/loki/api/v1/query_range"
EVENTS = {
    "http_request",
    "request_failed",
    "database_operation_failed",
    "transfer_committed",
    "transfer_replayed",
    "outbox_published",
    "outbox_publish_retry",
    "event_processed",
    "event_duplicate",
}
BUSINESS = ERROR_CODES - {"DATABASE_UNAVAILABLE", "DEPENDENCY_DEGRADED", "INTERNAL_ERROR"}


class EvidenceUnavailable(Exception):
    pass


def project_call(row: dict) -> Call | None:
    if (
        row.get("record_schema") != 1
        or row.get("event") != "http_request"
        or row.get("service") != "api"
        or row.get("route") not in ROUTES
    ):
        return None
    try:
        status = row["status_code"]
        if type(status) is not int:
            return None
        code, cls = row.get("error_code"), row.get("error_class")
        call = Call(
            id=row["call_id"],
            request_id=row.get("request_id") or None,
            trace_id=row.get("trace_id") or None,
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            method=row["method"],
            route=row["route"],
            status_code=status,
            duration_ms=row["duration_ms"],
            outcome="infrastructure_error"
            if status >= 500
            else "business_rejection"
            if status >= 400 and code in BUSINESS
            else "http_rejection"
            if status >= 400
            else "success",
            error_code=code if code in ERROR_CODES else None,
            error_class=cls if cls in ERROR_CLASSES else None,
            client_kind=row.get("client_kind")
            if row.get("client_kind") in ("dashboard", "locust")
            else "unknown",
        )
        if (
            call.completed_at < call.started_at
            or call.completed_at.timestamp() > datetime.now(timezone.utc).timestamp() + 5
        ):
            return None
        return call
    except (ValueError, TypeError, KeyError):
        return None


def log_rows(payload):
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return None
    rows = []
    for stream in payload.get("data", {}).get("result", [])[:100]:
        for stamp, line in stream.get("values", [])[:100]:
            try:
                row = json.loads(line)
                if isinstance(row, dict) and len(str(stamp)) == 19:
                    rows.append((int(stamp), row))
            except (ValueError, TypeError):
                continue
    return sorted(rows, key=lambda item: item[0], reverse=True)[:100]


async def list_calls(query: CallQuery, *, client=None) -> dict:
    if client is None:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as c:
            return await list_calls(query, client=c)
    now = datetime.now(timezone.utc)
    end = int(now.timestamp() * 1e9)
    start = int((now.timestamp() - query.lookback_seconds) * 1e9)
    excluded = set()
    cursor_stamp = None
    if query.cursor:
        parts = query.cursor.split(":", 1)
        cursor_stamp = int(parts[0])
        end = min(end, cursor_stamp)
        excluded = set(parts[1].split(",")) if len(parts) == 2 else set()
    expression = '{service="api"} | json | event="http_request" | record_schema=1 | route=~"/api/v1/(accounts|transfers).*"'
    if query.route:
        expression += ' | route="' + query.route + '"'
    if query.trace_id:
        expression += ' | trace_id="' + query.trace_id + '"'
    if excluded:
        expression += ' | call_id!~"^(' + "|".join(sorted(excluded)) + ')$"'
    if query.outcome == "slow":
        expression += " | duration_ms >= 500"
    elif query.outcome == "infrastructure_error":
        expression += " | status_code >= 500"
    elif query.outcome == "success":
        expression += " | status_code < 400"
    elif query.outcome in ("business_rejection", "http_rejection"):
        expression += " | status_code >= 400 | status_code < 500"
        if query.outcome == "business_rejection":
            expression += ' | error_code=~"' + "|".join(sorted(BUSINESS)) + '"'
        else:
            expression += ' | error_code!~"' + "|".join(sorted(BUSINESS)) + '"'
    payload = (
        await read(
            client,
            LOKI,
            LOGS_PATH,
            {
                "query": expression,
                "start": str(start),
                "end": str(end),
                "limit": query.limit + 1,
                "direction": "backward",
            },
        )
        if start <= end
        else {"status": "success", "data": {"result": []}}
    )
    rows = log_rows(payload)
    # Exclusion is also checked locally; IDs are unique per HTTP attempt, and
    # retaining a tied timestamp avoids dropping siblings received together.
    rows = [r for r in rows if r[1].get("call_id") not in excluded] if rows is not None else None
    items, seen = [], set()
    for stamp, raw in rows or []:
        call = project_call(raw)
        if not call or str(call.id) in seen or not start <= stamp <= end:
            continue
        if (
            query.trace_id
            and call.trace_id != query.trace_id
            or query.route
            and call.route != query.route
        ):
            continue
        if (
            query.outcome == "slow"
            and call.duration_ms < 500
            or query.outcome not in ("all", "slow")
            and call.outcome != query.outcome
        ):
            continue
        seen.add(str(call.id))
        items.append((stamp, call.model_dump(mode="json")))
    next_cursor, cursor_limited = None, False
    if len(items) > query.limit or rows and len(rows) >= query.limit + 1:
        boundary = items[query.limit - 1][0] if len(items) > query.limit else rows[-1][0]
        consumed = {item["id"] for stamp, item in items[: query.limit] if stamp == boundary}
        if len(items) <= query.limit:
            for stamp, raw in rows:
                if stamp == boundary:
                    try:
                        consumed.add(str(UUID(str(raw.get("call_id")))))
                    except ValueError:
                        pass
        if boundary == cursor_stamp:
            consumed.update(excluded)
        if len(consumed) > 100:
            cursor_limited = True
        elif consumed:
            next_cursor = str(boundary) + ":" + ",".join(sorted(consumed))
        else:
            # No valid attempt ID exists at this boundary (malformed records).
            next_cursor = str(boundary - 1)
    return {
        "items": [item for _, item in items[: query.limit]],
        "next_cursor": next_cursor,
        "quality": {
            "status": "UNKNOWN" if rows is None or cursor_limited else "AVAILABLE",
            "source": "loki",
            "observed_at": now.isoformat(),
            "window_seconds": query.lookback_seconds,
        },
        "notice": "Pagination stopped at the safety bound for equal log timestamps; narrow the filters."
        if cursor_limited
        else "Request logs unavailable from Loki. An empty result is UNKNOWN, not healthy."
        if rows is None
        else "Server-observed calls only; log delivery may be delayed. Older records without call metadata and client requests that never reached the API are unavailable.",
    }


def span_id(value, length=16):
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[a-f0-9]{" + str(length) + r"}", value):
        return value
    try:
        raw = base64.b64decode(value, validate=True)
        return raw.hex() if len(raw) * 2 == length else None
    except ValueError:
        return None


def call_spans(payload, call: Call):
    """Trace identity is shared across HTTP attempts; select the exact call branch."""
    candidates = []
    for batch in ((payload or {}).get("batches") or (payload or {}).get("resourceSpans") or [])[
        :32
    ]:
        service = (
            attributes(batch.get("resource", {}).get("attributes", []))
            .get("service.name", {})
            .get("stringValue")
        )
        if service not in ("api", "outbox-relay", "event-worker"):
            continue
        for scope in (batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or [])[
            :32
        ]:
            for span in scope.get("spans", [])[:100]:
                attrs = attributes(span.get("attributes", []))
                marker = attrs.get("pulsepay.call_id", {}).get("stringValue")
                candidates.append((service, span, marker))
    selected = {
        sid
        for _, span, marker in candidates
        if marker == str(call.id) and (sid := span_id(span.get("spanId")))
    }
    # Parent chains may be returned out of order. A differently tagged HTTP attempt
    # starts a separate branch even when it shares this call's incoming trace.
    for _ in range(min(len(candidates), 64)):
        added = {
            sid
            for _, span, marker in candidates
            if marker in (None, str(call.id))
            and (sid := span_id(span.get("spanId")))
            and span_id(span.get("parentSpanId")) in selected
        } - selected
        if not added:
            break
        selected.update(added)
    return [
        (service, span)
        for service, span, marker in candidates
        if marker in (None, str(call.id)) and span_id(span.get("spanId")) in selected
    ]


def timeline(payload, call: Call):
    rows, omitted = [], 0
    for service, span in call_spans(payload, call):
        try:
            start, end = (
                int(span["startTimeUnixNano"]) / 1e9,
                int(span["endTimeUnixNano"]) / 1e9,
            )
            if (
                not call.started_at.timestamp() - 2 <= start <= call.completed_at.timestamp() + 300
                or not 0 <= end - start <= 900
            ):
                continue
            attrs = attributes(span.get("attributes", []))
            system = (attrs.get("db.system") or attrs.get("db.system.name") or {}).get(
                "stringValue"
            )
            status = (
                attrs.get("http.status_code") or attrs.get("http.response.status_code") or {}
            ).get("intValue")
            http = int(status) if status is not None else None
            if http is not None and not 100 <= http <= 599:
                http = None
            operation = (
                "database"
                if system in ("postgresql", "postgres")
                else "redis"
                if system == "redis"
                else "http"
                if http or "http.method" in attrs or "http.request.method" in attrs
                else "unknown"
            )
            name = span.get("name")
            if name not in ("transfer.transaction", "outbox.publish", "event.project"):
                name = {
                    "database": "PostgreSQL query",
                    "redis": "Redis operation",
                    "http": "HTTP handling",
                    "unknown": "Application span",
                }[operation]
            sid = span_id(span.get("spanId"))
            if sid is None:
                omitted += 1
                continue
            rows.append(
                {
                    "id": sid,
                    "parent_id": span_id(span.get("parentSpanId")),
                    "service": service,
                    "operation": operation,
                    "label": name,
                    "start_offset_ms": round((start - call.started_at.timestamp()) * 1000, 3),
                    "duration_ms": round((end - start) * 1000, 3),
                    "started_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                    "completed_at": datetime.fromtimestamp(end, timezone.utc).isoformat(),
                    "error": span.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR")
                    or (http or 0) >= 500,
                    "http_status": http,
                }
            )
        except (ValueError, TypeError, KeyError, OverflowError):
            omitted += 1
    rows.sort(key=lambda r: (r["start_offset_ms"], -r["duration_ms"], r["id"]))
    return {
        "status": "UNKNOWN"
        if not rows
        else "PARTIAL"
        if omitted or len(rows) > 64
        else "AVAILABLE",
        "spans": rows[:64],
        "omitted_spans": omitted + max(0, len(rows) - 64),
    }


def safe_log(raw, stamp):
    if (
        raw.get("service") not in ("api", "outbox-relay", "event-worker")
        or raw.get("event") not in EVENTS
    ):
        return None
    trace = raw.get("trace_id")
    return {
        "observed_at": datetime.fromtimestamp(stamp / 1e9, timezone.utc).isoformat(),
        "service": raw["service"],
        "event": raw["event"],
        "error_code": raw.get("error_code") if raw.get("error_code") in ERROR_CODES else None,
        "error_class": raw.get("error_class") if raw.get("error_class") in ERROR_CLASSES else None,
        "trace_id": trace
        if isinstance(trace, str) and re.fullmatch("[a-f0-9]{32}", trace)
        else None,
    }


async def call_detail(call_id, *, client=None) -> dict:
    uid = str(UUID(str(call_id)))
    if client is None:
        async with httpx.AsyncClient(
            timeout=2, trust_env=False, limits=httpx.Limits(max_connections=3)
        ) as c:
            return await call_detail(uid, client=c)
    now = datetime.now(timezone.utc)
    params = {
        "start": str(int((now.timestamp() - 86400) * 1e9)),
        "end": str(int(now.timestamp() * 1e9)),
        "limit": 100,
        "direction": "backward",
    }
    match = ' | json | call_id="' + uid + '"'
    data = log_rows(
        await read(
            client,
            LOKI,
            LOGS_PATH,
            {**params, "query": '{service="api"}' + match + ' | event="http_request"'},
        )
    )
    if data is None:
        raise EvidenceUnavailable("CALL_INVENTORY_UNAVAILABLE")
    call = next((c for _, raw in data if (c := project_call(raw)) and str(c.id) == uid), None)
    if call is None:
        raise LookupError("CALL_NOT_OBSERVED")
    params.update(
        start=str(int((call.started_at.timestamp() - 2) * 1e9)),
        end=str(int(min(now.timestamp(), call.completed_at.timestamp() + 300) * 1e9)),
    )
    payload, logs = await asyncio.gather(
        read(client, "http://tempo:3200", "/api/traces/" + call.trace_id)
        if call.trace_id
        else asyncio.sleep(0, result=None),
        read(
            client,
            LOKI,
            LOGS_PATH,
            {**params, "query": '{service=~"api|outbox-relay|event-worker"}' + match},
        ),
    )
    projected = []
    for stamp, raw in log_rows(logs) or []:
        if raw.get("call_id") == uid and (item := safe_log(raw, stamp)):
            projected.append(item)
    return {
        "call": call.model_dump(mode="json"),
        "trace": timeline(payload, call),
        "logs": [r for r in projected if r["service"] == "api"][:32],
        "related_events": [r for r in projected if r["service"] != "api"][:32],
        "logs_status": "AVAILABLE" if logs is not None else "UNKNOWN",
        "notice": "Asynchronous follow-up events are separate from the HTTP response. Missing traces/logs are unknown evidence, not proof of success.",
    }


async def call_state(detail, *, client=None):
    from decision_engine.adapters.call_metrics import historical_state

    return await historical_state(detail, client=client)


class CallEvidenceClient:
    async def request(self, path, params=None):
        async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
            async with c.stream(
                "GET", "http://evidence-reader:8093/api/v1/evidence" + path, params=params
            ) as response:
                if response.status_code == 404:
                    raise LookupError("CALL_NOT_OBSERVED")
                response.raise_for_status()
                parts, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 128 * 1024:
                        raise EvidenceUnavailable("EVIDENCE_RESPONSE_LIMIT")
                    parts.append(chunk)
                return json.loads(b"".join(parts))

    async def list(self, query):
        return await self.request("/calls", query.model_dump(exclude_none=True))

    async def detail(self, uid):
        return await self.request("/calls/" + str(UUID(str(uid))))

    async def state(self, uid):
        from decision_engine.models.live import LiveModelState

        return LiveModelState.model_validate(
            await self.request("/calls/" + str(UUID(str(uid))) + "/state")
        )
