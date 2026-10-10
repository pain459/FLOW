"""Observed signals only. No scenario, injector, target or expected cause leaks."""

import math
import time
import httpx
from chaos import state
from load_generator.controller.telemetry import prometheus_sample

EXTRA_QUERIES = {
    "api_p50_seconds": 'histogram_quantile(0.50,sum by(le)(rate(http_request_duration_seconds_bucket{job="api"}[30s])))',
    "api_p99_seconds": 'histogram_quantile(0.99,sum by(le)(rate(http_request_duration_seconds_bucket{job="api"}[30s])))',
    "api_5xx_rate": 'sum(rate(http_requests_total{job="api",status_class="5xx"}[30s]))',
    "api_4xx_rate": 'sum(rate(http_requests_total{job="api",status_class="4xx"}[30s]))',
    "db_observed_at": 'pulsepay_database_observed_timestamp_seconds{job="db-observer"}',
    "db_reachable": 'pulsepay_service_up{job="db-observer",service="db-observer"}',
    "worker_quarantine": 'sum(pulsepay_events_processed_total{job="event-worker",outcome="quarantined"})',
    "load_rps": "max(load_measured_rps)",
    "load_users": "max(load_active_users)",
    "load_target_users": "max(load_target_users)",
    "load_network_rx": "max(load_generator_network_received_bytes)",
    "load_network_tx": "max(load_generator_network_sent_bytes)",
    "load_timeouts": 'sum(load_outcome_requests_total{outcome="timeout",phase="measured"})',
}


def capture():
    with httpx.Client(timeout=2, trust_env=False) as client:
        metrics = prometheus_sample(client)
        for name, query in EXTRA_QUERIES.items():
            try:
                data = client.get(
                    "http://prometheus:9090/api/v1/query", params={"query": query}
                ).json()
                rows = data["data"]["result"]
                value = float(rows[0]["value"][1]) if len(rows) == 1 else None
                metrics["values"][name] = (
                    value if value is not None and math.isfinite(value) else None
                )
                if metrics["values"][name] is None:
                    metrics["gaps"].append(name)
            except (ValueError, KeyError, httpx.HTTPError):
                metrics["values"][name] = None
                metrics["gaps"].append(name)
        health, totals, api_response_ms = None, None, None
        started = time.monotonic()
        try:
            response = client.get("http://api:8080/health/dependencies")
            response.raise_for_status()
            health = response.json()
            api_response_ms = (time.monotonic() - started) * 1000
            dashboard = client.get("http://api:8080/api/v1/dashboard")
            dashboard.raise_for_status()
            totals = dashboard.json()["totals"]
        except (httpx.HTTPError, ValueError, KeyError):
            metrics["gaps"].append("api_health_or_dashboard_unavailable")
        return {
            "observed_at": state.now(),
            "observed_epoch": time.time(),
            "source": "Prometheus query plus actual HTTP probes",
            "window_seconds": 30,
            "metrics": metrics,
            "health": health,
            "totals": totals,
            "health_request_latency_ms": api_response_ms,
        }


def snapshot(sample, run_id, integrity=None):
    values = sample["metrics"]["values"]
    dependencies = (sample.get("health") or {}).get("dependencies", {})

    def reachable(name):
        status = dependencies.get(name, {}).get("status")
        return True if status == "HEALTHY" else False if status == "UNHEALTHY" else None

    rps, failures = values.get("api_rps"), values.get("api_5xx_rate")
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "observation_time": sample["observed_at"],
        "window_seconds": sample["window_seconds"],
        "system": "pulsepay",
        "api": {
            "rps": rps,
            "error_rate_pct": failures / rps * 100 if failures is not None and rps else None,
            "p50_ms": values.get("api_p50_seconds") * 1000
            if values.get("api_p50_seconds") is not None
            else None,
            "p95_ms": values.get("api_p95_seconds") * 1000
            if values.get("api_p95_seconds") is not None
            else None,
            "p99_ms": values.get("api_p99_seconds") * 1000
            if values.get("api_p99_seconds") is not None
            else None,
        },
        "database": {
            "reachable": reachable("postgres"),
            "connection_usage_pct": values.get("db_connection_usage_percent"),
            "lock_waits": values.get("db_lock_waits"),
            "deadlocks": values.get("db_deadlocks"),
        },
        "redis": {"reachable": reachable("redis")},
        "worker": {
            "outbox_pending": values.get("outbox_pending"),
            "consumer_lag_seconds": values.get("outbox_oldest_seconds"),
        },
        "integrity": {
            "status": (integrity or {}).get("status", "UNKNOWN"),
            "verified_at": (integrity or {}).get("finished_at"),
        },
        "load": {
            "rps": values.get("load_rps"),
            "active_users": values.get("load_users"),
            "configured_users": values.get("load_target_users"),
        },
        "missing_observations": sorted(set(sample["metrics"]["gaps"])),
        "available_investigations": [
            "inspect_api",
            "inspect_database",
            "inspect_redis",
            "inspect_workers",
            "collect_more_evidence",
            "escalate",
        ],
    }
