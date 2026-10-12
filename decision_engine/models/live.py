"""Symptom projection: arbitrary pasted content and correlation IDs never enter inference."""

import json
import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, StrictBool, field_validator

from decision_engine.models.contracts import StrictModel, normalize_answers
from decision_engine.models.observation import ModelState
from decision_engine.questions.first_response import questions, REASONS

SERVICES = {"api", "outbox-relay", "event-worker"}
ERROR_CODES = {
    "ACCOUNT_NOT_FOUND",
    "ACCOUNT_INACTIVE",
    "INSUFFICIENT_FUNDS",
    "INVALID_TRANSFER",
    "IDEMPOTENCY_CONFLICT",
    "DATABASE_UNAVAILABLE",
    "DEPENDENCY_DEGRADED",
    "INTERNAL_ERROR",
}
ERROR_CLASSES = {
    "TimeoutError",
    "TimeoutException",
    "ConnectTimeout",
    "ReadTimeout",
    "ConnectError",
    "ConnectionError",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "OperationalError",
    "InterfaceError",
    "DBAPIError",
    "PostgresError",
    "TooManyConnectionsError",
    "ValidationError",
    "ValueError",
    "RedisError",
    "ResponseError",
    "PoolTimeout",
}
SYMPTOMS = {"timeout", "connection_refused", "connection_reset", "validation_rejection"}


class Lookup(StrictModel):
    request_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    trace_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    lookback_seconds: int = Field(default=600, ge=30, le=900)


class Ask(Lookup):
    error_excerpt: str = Field(default="", max_length=4096)


class Span(StrictModel):
    service: Literal["api", "outbox-relay", "event-worker", "unknown"]
    operation: Literal["http", "database", "redis", "unknown"]
    duration_ms: float = Field(ge=0, le=900000)
    error: StrictBool | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    observed_at: datetime | None = None

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone required")
        return value


class Evidence(StrictModel):
    source: Literal["operator_report", "loki", "tempo"]
    quality: Literal["REPORTED", "FRESH", "HISTORICAL", "UNKNOWN"]
    observed_at: datetime | None = None
    lookback_seconds: int = Field(default=600, ge=30, le=900)
    error_codes: list[str] = Field(default_factory=list, max_length=8)
    error_classes: list[str] = Field(default_factory=list, max_length=8)
    symptoms: list[str] = Field(default_factory=list, max_length=4)
    http_statuses: list[int] = Field(default_factory=list, max_length=8)
    matched_records: int | None = Field(default=None, ge=0, le=100)
    spans: list[Span] = Field(default_factory=list, max_length=8)

    @field_validator("error_codes", "error_classes", "symptoms")
    @classmethod
    def known_labels(cls, v, info):
        allowed = {
            "error_codes": ERROR_CODES,
            "error_classes": ERROR_CLASSES,
            "symptoms": SYMPTOMS,
        }[info.field_name]
        if set(v) - allowed or len(v) != len(set(v)):
            raise ValueError("unregistered or duplicate symptom")
        return v

    @field_validator("http_statuses")
    @classmethod
    def valid_status(cls, values):
        if any(type(v) is not int or not 100 <= v <= 599 for v in values):
            raise ValueError("invalid HTTP status")
        return values

    @field_validator("observed_at")
    @classmethod
    def aware(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("timezone required")
        return v


class LiveModelState(ModelState):
    request_evidence: list[Evidence] = Field(default_factory=list, max_length=4)


def user_evidence(body: Ask) -> Evidence:
    text = body.error_excerpt
    # Extract enums rather than forwarding free text, even when it contains
    # instructions, SQL, credentials, experiment names or arbitrary metadata.
    symptoms = []
    for label, pattern in (
        ("timeout", r"\b(?:timed?\s*out|timeout|deadline)\b"),
        ("connection_refused", r"\bconnection\s+refused\b"),
        ("connection_reset", r"\bconnection\s+reset\b"),
        ("validation_rejection", r"\bvalidation\s+(?:error|failed)\b"),
    ):
        if re.search(pattern, text, re.I):
            symptoms.append(label)
    codes = sorted(code for code in ERROR_CODES if re.search(r"\b" + code + r"\b", text))
    classes = sorted(code for code in ERROR_CLASSES if re.search(r"\b" + code + r"\b", text))
    statuses = sorted(
        {int(v) for v in re.findall(r"\bHTTP(?:/\d(?:\.\d)?)?\s+([1-5]\d\d)\b", text, re.I)}
    )
    spans = []
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            spans = trace_evidence(payload, datetime.now(timezone.utc), body.lookback_seconds).spans
    except (ValueError, TypeError, AttributeError):
        pass
    return Evidence(
        source="operator_report",
        quality="REPORTED",
        lookback_seconds=body.lookback_seconds,
        error_codes=codes[:8],
        error_classes=classes[:8],
        symptoms=symptoms,
        http_statuses=statuses[:8],
        spans=spans,
    )


def attributes(rows):
    # Values are consumed only under known keys; no resource labels survive.
    return {r.get("key"): r.get("value", {}) for r in rows if isinstance(r, dict)}


def trace_evidence(payload: dict, now: datetime, lookback: int) -> Evidence:
    rows = []
    for batch in (payload.get("batches") or payload.get("resourceSpans") or [])[:32]:
        resource = attributes(batch.get("resource", {}).get("attributes", []))
        service = resource.get("service.name", {}).get("stringValue")
        if service not in SERVICES:
            continue
        for scope in (batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or [])[
            :32
        ]:
            for span in scope.get("spans", [])[:100]:
                try:
                    start_ns, end_ns = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
                    start, end = start_ns / 1e9, end_ns / 1e9
                    age = now.timestamp() - end
                    if not 0 <= age <= lookback or not 0 <= end - start <= lookback:
                        continue
                    attrs = attributes(span.get("attributes", []))
                    system = (attrs.get("db.system") or attrs.get("db.system.name") or {}).get(
                        "stringValue"
                    )
                    http = (
                        attrs.get("http.response.status_code")
                        or attrs.get("http.status_code")
                        or {}
                    )
                    status = int(http.get("intValue")) if http.get("intValue") is not None else None
                    operation = (
                        "database"
                        if system in ("postgresql", "postgres")
                        else "redis"
                        if system == "redis"
                        else "http"
                        if status or "http.request.method" in attrs or "http.method" in attrs
                        else "unknown"
                    )
                    flag = span.get("status", {}).get("code")
                    error = (
                        True
                        if flag in (2, "STATUS_CODE_ERROR")
                        else False
                        if flag in (0, 1, "STATUS_CODE_OK", "STATUS_CODE_UNSET")
                        else None
                    )
                    rows.append(
                        Span(
                            service=service,
                            operation=operation,
                            duration_ms=(end_ns - start_ns) / 1e6,
                            error=error,
                            http_status=status,
                            observed_at=datetime.fromtimestamp(end, timezone.utc),
                        )
                    )
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
    rows.sort(
        key=lambda s: (s.error is True or (s.http_status or 0) >= 400, s.duration_ms), reverse=True
    )
    count = min(len(rows), 100)
    statuses = sorted(
        {row.http_status for row in rows if row.http_status is not None}, reverse=True
    )[:8]
    # The summary includes statuses from parsed spans outside the retained sample.
    # Use the oldest represented observation, not a newer healthy span's timestamp.
    stamp = min(row.observed_at for row in rows) if rows else None
    rows = rows[:8]
    age = (now - stamp).total_seconds() if stamp else None
    return Evidence(
        source="tempo",
        quality="UNKNOWN" if age is None else "FRESH" if age <= 15 else "HISTORICAL",
        observed_at=stamp,
        lookback_seconds=lookback,
        matched_records=count,
        spans=rows,
        http_statuses=statuses,
    )


def answer_view(state: dict, raw_answers: dict) -> dict:
    normalized = normalize_answers({"answers": raw_answers}, questions())
    live = LiveModelState.model_validate(state)
    reasons = normalized["likely_reason"]
    symptoms = live.request_evidence
    codes = {code for item in symptoms for code in item.error_codes}
    classes = {code for item in symptoms for code in item.error_classes}
    reported = {code for item in symptoms for code in item.symptoms}
    statuses = {code for item in symptoms for code in item.http_statuses}
    spans = [span for item in symptoms for span in item.spans]
    support = {
        "database_connectivity": live.database.reachable is False
        or "DATABASE_UNAVAILABLE" in codes
        or bool(
            classes
            & {
                "PostgresError",
                "InterfaceError",
                "DBAPIError",
                "OperationalError",
                "TooManyConnectionsError",
            }
        )
        or any(s.operation == "database" and s.error for s in spans),
        "database_pressure": (live.database.connection_usage_pct or 0) >= 80
        or (live.database.lock_waits or 0) > 0
        or bool(classes & {"PoolTimeout", "TooManyConnectionsError"})
        or any(s.operation == "database" and s.duration_ms >= 500 for s in spans),
        "cache_or_event_connectivity": live.redis.reachable is False
        or "DEPENDENCY_DEGRADED" in codes
        or bool(classes & {"RedisError", "ResponseError"})
        or any(s.operation == "redis" and s.error for s in spans),
        "asynchronous_processing_delay": (live.worker.outbox_oldest_seconds or 0) >= 10
        or (live.worker.consumer_lag_messages or 0) > 0
        or (live.worker.pending_messages or 0) > 0,
        "business_or_validation_rejection": bool(
            codes
            & (ERROR_CODES - {"DATABASE_UNAVAILABLE", "DEPENDENCY_DEGRADED", "INTERNAL_ERROR"})
        )
        or bool(statuses & {400, 404, 409, 422})
        or "ValidationError" in classes,
        "application_error": "INTERNAL_ERROR" in codes
        or "ValueError" in classes
        or (live.api.error_rate_pct or 0) > 0
        or 500 in statuses,
        "transport_or_deadline": bool(
            reported & {"timeout", "connection_refused", "connection_reset"}
        )
        or bool(
            classes
            & {
                "TimeoutError",
                "TimeoutException",
                "ConnectTimeout",
                "ReadTimeout",
                "ConnectError",
                "ConnectionError",
                "ConnectionRefusedError",
                "ConnectionResetError",
            }
        )
        or bool(statuses & {408, 504})
        or any(s.duration_ms >= 500 for s in spans),
        "insufficient_evidence": True,
    }
    support["no_observed_failure"] = (
        not any(support[k] for k in support if k != "insufficient_evidence")
        and live.database.reachable is True
        and live.redis.reachable is True
        and live.api.error_rate_pct == 0
        and live.integrity.status == "PASS"
        and not (codes or classes or reported or any(v >= 400 for v in statuses))
        and not any(s.error is True or (s.http_status or 0) >= 400 for s in spans)
    )
    facts = []
    if live.database.reachable is False:
        facts.append("Current database reachability probe failed")
    if live.redis.reachable is False:
        facts.append("Current Redis reachability probe failed")
    if live.database.connection_usage_pct is not None and live.database.connection_usage_pct >= 80:
        facts.append(f"Database connection usage {live.database.connection_usage_pct:.1f}%")
    if live.database.lock_waits:
        facts.append(f"Database lock waits {live.database.lock_waits:g}")
    if live.api.error_rate_pct:
        facts.append(
            f"Current HTTP 5xx rate {live.api.error_rate_pct:.1f}% over {live.window_seconds}s"
        )
    if live.worker.outbox_oldest_seconds:
        facts.append(f"Oldest pending outbox event {live.worker.outbox_oldest_seconds:.1f}s")
    for e in symptoms:
        if e.error_codes or e.error_classes or e.symptoms or e.http_statuses:
            facts.append(
                f"{e.source} ({e.quality}): "
                + ", ".join(
                    [
                        *e.error_codes,
                        *e.error_classes,
                        *e.symptoms,
                        *(f"HTTP {v}" for v in e.http_statuses),
                    ]
                )
            )
        for s in e.spans:
            if s.error or s.duration_ms >= 500:
                facts.append(
                    f"{e.source} ({e.quality}): {s.service}/{s.operation}, {s.duration_ms:.1f}ms, error={s.error}"
                )
    unknowns = list(live.missing)
    unknowns += [
        f"{e.source}: no correlated evidence in selected window"
        for e in symptoms
        if e.quality == "UNKNOWN"
    ]
    if any(e.source == "operator_report" for e in symptoms):
        unknowns.append("Pasted symptoms are operator-reported; arbitrary text is not sent to Laya")
    unknowns.append("Injection cause and restoration state are not available to Laya")
    proposal = reasons["choice"]
    selected = proposal if support[proposal] else "insufficient_evidence"
    override = (
        None
        if selected == proposal
        else "MODEL_HYPOTHESIS_NOT_SUPPORTED"
        if facts
        else "NO_SUPPORTING_EVIDENCE"
    )
    return {
        "reason": REASONS[selected],
        "reason_code": selected,
        "proposal_reason_code": proposal,
        "override_reason": override,
        "suspected_subsystem": normalized["suspected_subsystem"]["choice"],
        "hypotheses": [
            {
                "reason": REASONS[k],
                "reason_code": k,
                "model_score": p,
                "symptom_support": support[k],
            }
            for k, p in sorted(
                reasons["probabilities"].items(), key=lambda item: (-item[1], item[0])
            )[:3]
        ],
        "evidence": facts,
        "unknowns": unknowns,
        "needs_more_evidence_probability": normalized["needs_more_evidence"]["noul"],
        "next_check": normalized["next_diagnostic_tool"]["choice"],
        "severity_expected_ordinal": normalized["incident_severity"]["score"],
        "confirmed_cause": False,
        "recommendation_only": True,
        "executed_actions": 0,
        "observed_at": live.observed_at.isoformat(),
        "window_seconds": live.window_seconds,
        "score_interpretation": "Uncalibrated Laya suitability scores; not probabilities of a confirmed cause",
    }
