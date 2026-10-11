"""Observed signals only. No scenario, injector, target or expected cause leaks."""

import math
import time
import os
import json
import stat
from pathlib import Path
import httpx
from chaos import state
from load_generator.controller.telemetry import prometheus_sample
from chaos.observation_contract import build_snapshot, validate_snapshot, valid_run_id, MAX_BYTES

EXTRA_QUERIES = {
    "api_p50_seconds": 'histogram_quantile(0.50,sum by(le)(rate(http_request_duration_seconds_bucket{job="api"}[30s])))',
    "api_p99_seconds": 'histogram_quantile(0.99,sum by(le)(rate(http_request_duration_seconds_bucket{job="api"}[30s])))',
    "api_5xx_rate": 'sum(rate(http_requests_total{job="api",status_class="5xx"}[30s]))',
    "api_4xx_rate": 'sum(rate(http_requests_total{job="api",status_class="4xx"}[30s]))',
    "db_observed_at": 'pulsepay_database_observed_timestamp_seconds{job="db-observer"}',
    "worker_observed_at": 'pulsepay_component_observed_timestamp_seconds{job="event-worker",service="event-worker"}',
    "relay_observed_at": 'pulsepay_component_observed_timestamp_seconds{job="outbox-relay",service="outbox-relay"}',
    "db_reachable": 'pulsepay_service_up{job="db-observer",service="db-observer"}',
    "worker_quarantine": 'sum(pulsepay_events_processed_total{job="event-worker",outcome="quarantined"})',
    "consumer_oldest_seconds": 'pulsepay_consumer_oldest_pending_age_seconds{job="event-worker"}',
    "load_rps": "max by(job)(load_measured_rps and on(job) (load_active_users > 0))",
    "load_users": "max(load_active_users and on(job) (load_active_users > 0))",
    "load_target_users": "max(load_target_users and on(job) (load_active_users > 0))",
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
                if name == "load_rps" and len(rows) == 1:
                    job = rows[0].get("metric", {}).get("job")
                    if job in ("load", "locust"):
                        metrics["active_load_job"] = job
                if metrics["values"][name] is None:
                    metrics["gaps"].append(name)
            except (ValueError, KeyError, httpx.HTTPError):
                metrics["values"][name] = None
                metrics["gaps"].append(name)
        health, totals, api_response_ms, health_observed_at = None, None, None, None
        started = time.monotonic()
        try:
            response = client.get("http://api:8080/health/dependencies")
            response.raise_for_status()
            health = response.json()
            health_observed_at = state.now()
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
            "health_observed_at": health_observed_at,
        }


def snapshot(sample, run_id, integrity=None):
    return build_snapshot(sample, run_id, integrity)


def publish(sample, run_id, integrity=None, *, root=None):
    value = validate_snapshot(snapshot(sample, run_id, integrity))
    configured = root if root is not None else os.getenv("OBSERVATION_DIR")
    if configured is None:
        return value
    if not valid_run_id(run_id):
        raise ValueError("Unsafe observation identifier")
    root = Path(configured)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe observation namespace")
    directory = root / run_id
    directory.mkdir(exist_ok=True)
    if root.is_symlink() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("Unsafe observation namespace")
    line = (json.dumps(value, allow_nan=False) + "\n").encode()
    descriptor = os.open(
        directory / "sequence.jsonl",
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
        0o660,
    )
    with os.fdopen(descriptor, "ab") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size + len(line) > MAX_BYTES:
            raise ValueError("Unsafe or oversized observation sequence")
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())
    state.write(directory / "latest.json", value)
    state.write(root / "latest.json", {"run_id": run_id})
    return value
