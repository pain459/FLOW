"""Fixed, bounded GET-only observations. No chaos API, files, credentials or SQL."""

import asyncio
import json
import math
from datetime import datetime, timezone

import httpx

from chaos.observation_contract import build_snapshot, epoch
from decision_engine.models.live import Lookup, Evidence, ERROR_CLASSES, trace_evidence
from decision_engine.models.observation import from_snapshot
from decision_engine.models.live import LiveModelState

JOBS = {"api", "db-observer", "event-worker", "outbox-relay", "verifier", "load", "locust"}
ROUTES = 'route=~"/api/v1/accounts.*|/api/v1/transfers.*"'
QUERIES = {
    "api_rps": f'sum(rate(http_requests_total{{job="api",{ROUTES}}}[30s]))',
    "api_5xx_rate": f'sum(rate(http_requests_total{{job="api",status_class="5xx",{ROUTES}}}[30s]))',
    **{
        f"api_p{p}_seconds": f'histogram_quantile({p / 100},sum by(le)(rate(http_request_duration_seconds_bucket{{job="api"}}[30s])))'
        for p in (50, 95, 99)
    },
    "db_connection_usage_percent": 'pulsepay_database_connection_usage_percent{job="db-observer"}',
    "db_lock_waits": 'pulsepay_database_lock_waits{job="db-observer"}',
    "db_deadlocks": 'pulsepay_database_deadlocks{job="db-observer"}',
    "db_observed_at": 'pulsepay_database_observed_timestamp_seconds{job="db-observer"}',
    "db_reachable": 'pulsepay_service_up{job="db-observer",service="db-observer"}',
    "worker_observed_at": 'pulsepay_component_observed_timestamp_seconds{job="event-worker",service="event-worker"}',
    "relay_observed_at": 'pulsepay_component_observed_timestamp_seconds{job="outbox-relay",service="outbox-relay"}',
    "outbox_pending": 'pulsepay_outbox_pending{job="outbox-relay"}',
    "outbox_oldest_seconds": 'pulsepay_outbox_oldest_age_seconds{job="outbox-relay"}',
    "worker_lag": 'pulsepay_consumer_lag{job="event-worker"}',
    "worker_pending": 'pulsepay_consumer_pending{job="event-worker"}',
    "consumer_oldest_seconds": 'pulsepay_consumer_oldest_pending_age_seconds{job="event-worker"}',
    "load_rps": "max(load_measured_rps and on(job) (load_active_users > 0))",
    "load_users": "max(load_active_users and on(job) (load_active_users > 0))",
    "load_target_users": "max(load_target_users and on(job) (load_active_users > 0))",
}
TARGETS = {
    "http://prometheus:9090": {"/api/v1/query", "/api/v1/targets"},
    "http://api:8080": {"/health/dependencies"},
    "http://verifier:9100": {"/report"},
    "http://loki:3100": {"/loki/api/v1/query_range"},
    "http://tempo:3200": set(),  # exact hex trace path validated below
}


async def read(client, base, path, params=None):
    if base not in TARGETS or not (
        path in TARGETS[base]
        or base == "http://tempo:3200"
        and path.startswith("/api/traces/")
        and len(path.removeprefix("/api/traces/")) == 32
        and all(c in "0123456789abcdef" for c in path.removeprefix("/api/traces/"))
    ):
        raise ValueError("evidence target outside allowlist")
    try:
        async with client.stream(
            "GET",
            base + path,
            params=params,
            timeout=2,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 512 * 1024:
                    return None
                chunks.append(chunk)
            result = json.loads(b"".join(chunks))
            return result if isinstance(result, dict) else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


async def logs(client, lookup, now):
    suffix = ""
    if lookup.request_id:
        suffix += ' | json | request_id="' + lookup.request_id + '"'
    if lookup.trace_id:
        suffix += (" | json" if not suffix else "") + ' | trace_id="' + lookup.trace_id + '"'
    data = await read(
        client,
        "http://loki:3100",
        "/loki/api/v1/query_range",
        {
            "query": '{service=~"api|outbox-relay|event-worker"}' + suffix,
            "start": str(int((now.timestamp() - lookup.lookback_seconds) * 1e9)),
            "end": str(int(now.timestamp() * 1e9)),
            "limit": 100,
            "direction": "backward",
        },
    )
    stamp, trace_id, classes, count = None, lookup.trace_id, set(), 0
    for stream in ((data or {}).get("data", {}).get("result", []))[:100]:
        for timestamp, line in stream.get("values", [])[:100]:
            try:
                row = json.loads(line)
                when = datetime.fromtimestamp(int(timestamp) / 1e9, timezone.utc)
                if not 0 <= (now - when).total_seconds() <= lookup.lookback_seconds or row.get(
                    "service"
                ) not in ("api", "outbox-relay", "event-worker"):
                    continue
                # Defensive equality checks, independent of Loki filtering.
                if lookup.request_id and row.get("request_id") != lookup.request_id:
                    continue
                if lookup.trace_id and row.get("trace_id") != lookup.trace_id:
                    continue
                count += 1
                # Conservative oldest-match time: recent healthy logs cannot
                # make an older retained error class look current.
                stamp = min(stamp, when) if stamp else when
                cls = row.get("error_class")
                if cls in ERROR_CLASSES:
                    classes.add(cls)
                candidate = row.get("trace_id")
                if (
                    trace_id is None
                    and isinstance(candidate, str)
                    and len(candidate) == 32
                    and all(c in "0123456789abcdef" for c in candidate)
                ):
                    trace_id = candidate
            except (ValueError, TypeError, OverflowError):
                continue
    quality = (
        "UNKNOWN"
        if stamp is None
        else "FRESH"
        if (now - stamp).total_seconds() <= 15
        else "HISTORICAL"
    )
    return Evidence(
        source="loki",
        quality=quality,
        observed_at=stamp,
        lookback_seconds=lookup.lookback_seconds,
        matched_records=min(count, 100) if data else None,
        error_classes=sorted(classes)[:8],
    ), trace_id


async def collect(lookup: Lookup, *, client=None) -> LiveModelState:
    if client is None:
        async with httpx.AsyncClient(
            timeout=2, trust_env=False, limits=httpx.Limits(max_connections=6)
        ) as c:
            return await collect(lookup, client=c)
    limiter = asyncio.Semaphore(6)

    async def query(name, expression):
        async with limiter:
            result = await read(
                client, "http://prometheus:9090", "/api/v1/query", {"query": expression}
            )
        try:
            rows = result["data"]["result"] if result["status"] == "success" else []
            value = float(rows[0]["value"][1]) if len(rows) == 1 else None
            return name, value if value is not None and math.isfinite(
                value
            ) and value >= 0 else None
        except (ValueError, TypeError, KeyError):
            return name, None

    # The caller also bounds total collection at ten seconds.
    targets, health, verifier, values = await asyncio.gather(
        read(client, "http://prometheus:9090", "/api/v1/targets"),
        read(client, "http://api:8080", "/health/dependencies"),
        read(client, "http://verifier:9100", "/report"),
        asyncio.gather(*(query(k, q) for k, q in QUERIES.items())),
    )
    now = datetime.now(timezone.utc)
    scrapes = {}
    for target in ((targets or {}).get("data", {}).get("activeTargets", []))[:100]:
        job = target.get("labels", {}).get("job")
        if job in JOBS:
            stamp = target.get("lastScrape")
            scrapes[job] = {
                "health": "up" if target.get("health") == "up" else "unknown",
                "last_scrape": stamp if epoch(stamp) is not None else None,
            }
    # A degraded cache is an observed failed optional connection, not healthy.
    safe_health = {"dependencies": {}}
    for name in ("postgres", "redis"):
        status = (health or {}).get("dependencies", {}).get(name, {}).get("status")
        if name == "redis" and status == "DEGRADED":
            status = "UNHEALTHY"
        safe_health["dependencies"][name] = {
            "status": status if status in ("HEALTHY", "UNHEALTHY") else "UNKNOWN"
        }
    sample = {
        "observed_at": now.isoformat(),
        "window_seconds": 30,
        "health": safe_health,
        "health_observed_at": (health or {}).get("observed_at"),
        "metrics": {"scrapes": scrapes, "values": dict(values)},
    }
    integrity = {
        "status": (verifier or {}).get("status", "UNKNOWN"),
        "finished_at": (verifier or {}).get("finished_at"),
    }
    # No experiment ID is used for collection. The shared schema's required opaque
    # identifier is removed immediately by the qualified projection.
    snapshot = build_snapshot(sample, "chaos-observation", integrity)
    base = from_snapshot(snapshot).model_dump(mode="json")
    if (
        base["database"]["reachable"] is None
        and base["source_quality"]["db-observer"] == "FRESH"
        and dict(values).get("db_reachable") in (0, 1)
    ):
        base["database"]["reachable"] = bool(dict(values)["db_reachable"])
        base["missing"] = [v for v in base["missing"] if v != "database.reachable"]
    evidence = []
    if lookup.request_id or lookup.trace_id:
        log, trace_id = await logs(client, lookup, now)
        evidence.append(log)
        if trace_id:
            payload = await read(client, "http://tempo:3200", "/api/traces/" + trace_id)
            evidence.append(
                trace_evidence(payload or {}, datetime.now(timezone.utc), lookup.lookback_seconds)
            )
    return LiveModelState(**base, request_evidence=evidence)


class LiveEvidenceClient:
    async def collect(self, lookup: Lookup):
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            async with client.stream(
                "POST",
                "http://evidence-reader:8093/api/v1/evidence/collect",
                json=lookup.model_dump(mode="json"),
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 16384:
                        raise ValueError("evidence response too large")
                    chunks.append(chunk)
        return LiveModelState.model_validate_json(b"".join(chunks))
