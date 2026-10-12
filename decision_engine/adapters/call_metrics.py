"""Historical metrics evaluated at call completion, with contemporaneous quality."""

import asyncio
import math
from datetime import datetime, timezone

import httpx

from decision_engine.adapters.live_evidence import QUERIES, read
from decision_engine.models.calls import Call
from decision_engine.models.live import Evidence, LiveModelState, Span
from decision_engine.models.observation import API, Database, Redis, Worker, Workload, Integrity

JOBS = ("api", "db-observer", "outbox-relay", "event-worker", "verifier", "load", "locust")
HISTORICAL = {
    **QUERIES,
    "redis_reachable": 'pulsepay_service_up{job="api",service="redis"}',
    "integrity_status": 'pulsepay_verification_status{job="verifier",check="overall"}',
    "integrity_observed_at": 'pulsepay_component_observed_timestamp_seconds{job="verifier",service="verifier"}',
    **{f"up_{job}": f'up{{job="{job}"}}' for job in JOBS},
    **{f"stamp_{job}": f'timestamp(up{{job="{job}"}})' for job in JOBS},
}


async def historical_state(detail, *, client=None) -> LiveModelState:
    if client is None:
        async with httpx.AsyncClient(
            timeout=2, trust_env=False, limits=httpx.Limits(max_connections=6)
        ) as c:
            return await historical_state(detail, client=c)
    call = Call.model_validate(detail["call"])
    at = call.completed_at.timestamp()
    limiter = asyncio.Semaphore(6)

    async def query(key, expression):
        async with limiter:
            data = await read(
                client,
                "http://prometheus:9090",
                "/api/v1/query",
                {"query": expression, "time": str(at)},
            )
        try:
            rows = data["data"]["result"] if data["status"] == "success" else []
            stamp, raw = rows[0]["value"] if len(rows) == 1 else (None, None)
            value = float(raw)
            return key, value if math.isfinite(value) and value >= 0 and abs(
                float(stamp) - at
            ) <= 1 else None
        except (ValueError, TypeError, KeyError):
            return key, None

    values = dict(
        await asyncio.gather(*(query(key, expression) for key, expression in HISTORICAL.items()))
    )
    quality, provenance = {}, {}
    for job in JOBS:
        if job == "locust":
            continue
        actual = "locust" if job == "load" and values.get("up_load") != 1 else job
        stamp = values.get("stamp_" + actual)
        producer = values.get(
            {
                "db-observer": "db_observed_at",
                "outbox-relay": "relay_observed_at",
                "event-worker": "worker_observed_at",
                "verifier": "integrity_observed_at",
            }.get(job, "")
        )
        if job in ("db-observer", "outbox-relay", "event-worker", "verifier"):
            stamp = min(stamp, producer) if stamp is not None and producer is not None else None
        age = at - stamp if stamp is not None and 0 <= stamp <= at else None
        bound = 60 if job == "verifier" else 15
        quality[job] = (
            "UNKNOWN"
            if values.get("up_" + actual) != 1 or age is None
            else "FRESH"
            if age <= bound
            else "STALE"
        )
        provenance[job] = {
            "observed_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat()
            if age is not None
            else None,
            "age_seconds": age,
            "max_age_seconds": bound,
        }
    quality["dependencies"], provenance["dependencies"] = quality["api"], provenance["api"].copy()
    quality["integrity"], provenance["integrity"] = (
        quality["verifier"],
        provenance["verifier"].copy(),
    )

    def metric(key, job):
        return values.get(key) if quality[job] == "FRESH" else None

    def reach(key, job):
        value = metric(key, job)
        return bool(value) if value in (0, 1) else None

    rps, errors = metric("api_rps", "api"), metric("api_5xx_rate", "api")
    api = API(
        rps=rps,
        error_rate_pct=min(100, errors / rps * 100) if errors is not None and rps else None,
        **{
            f"p{p}_ms": v * 1000 if (v := metric(f"api_p{p}_seconds", "api")) is not None else None
            for p in (50, 95, 99)
        },
    )
    usage = metric("db_connection_usage_percent", "db-observer")
    db = Database(
        reachable=reach("db_reachable", "db-observer"),
        connection_usage_pct=usage if usage is not None and usage <= 100 else None,
        lock_waits=metric("db_lock_waits", "db-observer"),
        deadlocks=metric("db_deadlocks", "db-observer"),
    )
    redis = Redis(reachable=reach("redis_reachable", "api"))
    worker = Worker(
        outbox_pending=metric("outbox_pending", "outbox-relay"),
        outbox_oldest_seconds=metric("outbox_oldest_seconds", "outbox-relay"),
        consumer_lag_messages=metric("worker_lag", "event-worker"),
        pending_messages=metric("worker_pending", "event-worker"),
        oldest_pending_age_seconds=metric("consumer_oldest_seconds", "event-worker"),
    )
    workload = Workload(
        rps=metric("load_rps", "load"),
        active_users=metric("load_users", "load"),
        configured_users=metric("load_target_users", "load"),
    )
    integrity = Integrity(
        status={0: "PASS", 1: "FAIL", 2: "UNKNOWN", 3: "DEGRADED"}.get(
            metric("integrity_status", "integrity"), "UNKNOWN"
        ),
        verified_at=provenance["integrity"]["observed_at"],
    )
    missing = [
        f"{prefix}.{key}"
        for prefix, model in (
            ("api", api),
            ("database", db),
            ("redis", redis),
            ("worker", worker),
            ("load", workload),
        )
        for key, value in model.model_dump().items()
        if value is None
    ]
    if integrity.status == "UNKNOWN":
        missing.append("integrity.status")
    evidence = [
        Evidence(
            source="loki",
            quality="HISTORICAL",
            observed_at=call.completed_at,
            lookback_seconds=30,
            matched_records=1,
            error_codes=[call.error_code] if call.error_code else [],
            error_classes=[call.error_class] if call.error_class else [],
            http_statuses=[call.status_code],
        )
    ]
    # Later worker processing is displayed to the operator, but never used to
    # explain an earlier call. No IDs/labels/SQL/messages survive this projection.
    spans = []
    for row in detail.get("trace", {}).get("spans", []):
        try:
            ended = datetime.fromisoformat(row["completed_at"])
            if ended <= call.completed_at and row["service"] == "api":
                spans.append(
                    Span(
                        service="api",
                        operation=row["operation"],
                        duration_ms=row["duration_ms"],
                        error=row["error"],
                        http_status=row.get("http_status"),
                        observed_at=ended,
                    )
                )
        except (ValueError, TypeError, KeyError):
            continue
    spans.sort(
        key=lambda s: (s.error is True or (s.http_status or 0) >= 400, s.duration_ms), reverse=True
    )
    if spans:
        evidence.append(
            Evidence(
                source="tempo",
                quality="HISTORICAL",
                observed_at=min(s.observed_at for s in spans),
                lookback_seconds=30,
                spans=spans[:8],
                matched_records=min(len(spans), 100),
            )
        )
    return LiveModelState(
        observed_at=call.completed_at,
        window_seconds=30,
        api=api,
        database=db,
        redis=redis,
        worker=worker,
        workload=workload,
        integrity=integrity,
        source_quality=quality,
        provenance=provenance,
        missing=sorted(missing),
        request_evidence=evidence,
    )
