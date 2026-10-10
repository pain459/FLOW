import math
import time
from datetime import datetime, timezone
import httpx
from prometheus_client.core import (
    GaugeMetricFamily,
    CounterMetricFamily,
    HistogramMetricFamily,
)

QUERIES = {
    "api_http_counter": 'sum(http_requests_total{job="api",route=~"/api/v1/accounts.*|/api/v1/transfers.*"})',
    "api_rps": 'sum(rate(http_requests_total{job="api",route=~"/api/v1/accounts.*|/api/v1/transfers.*"}[30s]))',
    "api_5xx_counter": 'sum(http_requests_total{job="api",status_class="5xx"})',
    "api_p95_seconds": 'histogram_quantile(0.95,sum by(le)(rate(http_request_duration_seconds_bucket{job="api"}[30s])))',
    "db_checked_out": 'pulsepay_db_pool_checked_out{job="api"}',
    "db_pool_wait_p95_seconds": 'histogram_quantile(0.95,sum by(le)(rate(pulsepay_db_pool_wait_seconds_bucket{job="api"}[30s])))',
    "outbox_pending": 'pulsepay_outbox_pending{job="outbox-relay"}',
    "outbox_oldest_seconds": 'pulsepay_outbox_oldest_age_seconds{job="outbox-relay"}',
    "worker_lag": 'pulsepay_consumer_lag{job="event-worker"}',
    "worker_pending": 'pulsepay_consumer_pending{job="event-worker"}',
    "worker_effects_counter": 'sum(pulsepay_events_processed_total{job="event-worker",outcome="processed"})',
    "worker_retries_counter": 'sum(pulsepay_events_processed_total{job="event-worker",outcome="retry"})',
    "cache_hits_counter": 'pulsepay_cache_hits_total{job="api"}',
    "cache_misses_counter": 'pulsepay_cache_misses_total{job="api"}',
    "redis_failures_counter": 'sum(pulsepay_redis_operations_total{job="api",outcome="failure"})',
    "verifier_status": 'pulsepay_verification_status{job="verifier",check="overall"}',
    "db_connections": 'pulsepay_database_connections{job="db-observer"}',
    "db_connection_usage_percent": 'pulsepay_database_connection_usage_percent{job="db-observer"}',
    "db_lock_waits": 'pulsepay_database_lock_waits{job="db-observer"}',
    "db_oldest_lock_wait_seconds": 'pulsepay_database_oldest_lock_wait_seconds{job="db-observer"}',
    "db_deadlocks": 'pulsepay_database_deadlocks{job="db-observer"}',
    "db_long_running_queries": 'pulsepay_database_long_running_queries{job="db-observer"}',
    "db_statement_calls": 'pulsepay_database_statement_calls{job="db-observer"}',
    "db_statement_execution_seconds": 'pulsepay_database_statement_execution_seconds{job="db-observer"}',
    "db_statement_max_seconds": 'pulsepay_database_statement_max_duration_seconds{job="db-observer"}',
    "db_slow_statement_fingerprints": 'pulsepay_database_slow_statement_fingerprints{job="db-observer"}',
}
CORE_JOBS = {"api", "outbox-relay", "event-worker", "verifier", "db-observer"}


def prometheus_sample(client: httpx.Client) -> dict:
    result = {"values": {}, "gaps": [], "scrapes": {}}
    try:
        response = client.get("http://prometheus:9090/api/v1/targets")
        response.raise_for_status()
        targets = response.json()["data"]["activeTargets"]
        for target in targets:
            job = target["labels"]["job"]
            result["scrapes"][job] = {
                "health": target["health"],
                "last_scrape": target.get("lastScrape"),
            }
        for job in CORE_JOBS:
            observed = result["scrapes"].get(job, {})
            stamp = observed.get("last_scrape")
            fresh = (
                stamp
                and (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                ).total_seconds()
                <= 15
            )
            if observed.get("health") != "up" or not fresh:
                result["gaps"].append("scrape:" + job)
        for name, query in QUERIES.items():
            response = client.get("http://prometheus:9090/api/v1/query", params={"query": query})
            response.raise_for_status()
            data = response.json()
            values = data["data"]["result"] if data["status"] == "success" else []
            value = float(values[0]["value"][1]) if len(values) == 1 else None
            result["values"][name] = value if value is not None and math.isfinite(value) else None
            if value is None:
                result["gaps"].append(name)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result["gaps"].append("PROMETHEUS_UNAVAILABLE_OR_INVALID")
    return result


class LoadCollector:
    def __init__(self, profile):
        self.profile, self.stats, self.users, self.target, self.status = (
            profile,
            {},
            0,
            0,
            0,
        )
        self.resources = {}
        self.container_resources = {}
        self.verification = {}
        self.measured_rps = None

    def collect(self):
        requests = CounterMetricFamily(
            "load_requests_total",
            "Real HTTP attempts",
            labels=["operation", "status_class", "outcome", "phase"],
        )
        histogram = HistogramMetricFamily(
            "load_request_duration_seconds",
            "HTTP latency",
            labels=["operation", "phase"],
        )
        logical = CounterMetricFamily(
            "load_logical_transfers_total",
            "Logical outcomes",
            labels=["result", "phase"],
        )
        offered = CounterMetricFamily(
            "load_offered_operations_total",
            "Closed-loop selected operations",
            labels=["phase"],
        )
        replays = CounterMetricFamily(
            "load_idempotency_replays_total",
            "Safe replay outcomes",
            labels=["result", "phase"],
        )
        outcomes = CounterMetricFamily(
            "load_outcome_requests_total",
            "Classified HTTP outcomes including observed zero counts",
            labels=["outcome", "phase"],
        )
        for phase, stats in self.stats.items():
            for outcome in (
                "success",
                "replay",
                "business_rejection",
                "expected_rejection",
                "infrastructure_failure",
                "timeout",
                "contract_error",
            ):
                outcomes.add_metric([outcome, phase], stats.get("outcomes", {}).get(outcome, 0))
            for label, count in stats.get("labels", {}).items():
                requests.add_metric([*label.split("|"), phase], count)
            for operation in stats.get("operations", {}):
                durations = {
                    int(label.split(":", 1)[1]) / 1000: count
                    for label, count in stats.get("operation_latencies", {}).items()
                    if label.startswith(operation + ":")
                }
                boundaries = [
                    0.005,
                    0.01,
                    0.025,
                    0.05,
                    0.1,
                    0.25,
                    0.5,
                    1,
                    2,
                    5,
                    10,
                    float("inf"),
                ]
                buckets = [
                    (
                        str(boundary),
                        sum(count for latency, count in durations.items() if latency <= boundary),
                    )
                    for boundary in boundaries
                ]
                buckets[-1] = ("+Inf", sum(durations.values()))
                histogram.add_metric(
                    [operation, phase],
                    buckets,
                    sum(latency * count for latency, count in durations.items()),
                )
            for name in (
                "logical_attempts",
                "confirmed_commits",
                "logical_rejections",
                "unknown_outcomes",
            ):
                logical.add_metric([name, phase], stats.get(name, 0))
            offered.add_metric([phase], stats.get("offered", 0))
            replays.add_metric(["confirmed", phase], stats.get("duplicate_replays", 0))
        yield requests
        yield histogram
        yield logical
        yield offered
        yield replays
        yield outcomes
        weights = GaugeMetricFamily(
            "load_configured_operation_weight",
            "Configured logical operation weights",
            labels=["operation"],
        )
        for operation, weight in self.profile.mix.items():
            weights.add_metric([operation], weight)
        yield weights
        for name, value in (
            ("load_active_users", self.users),
            ("load_target_users", self.target),
            ("load_users_spawn_rate", self.profile.spawn_rate_users_per_second),
            ("load_measured_rps", self.measured_rps),
            ("load_generator_memory_bytes", self.resources.get("memory_bytes")),
            ("load_generator_cpu_limit", self.resources.get("cpu_limit")),
            ("load_generator_cpu_utilization", self.resources.get("cpu_utilization")),
            ("load_generator_network_received_bytes", self.resources.get("network_received_bytes")),
            ("load_generator_network_sent_bytes", self.resources.get("network_sent_bytes")),
        ):
            metric = GaugeMetricFamily(name, name)
            if value is not None:
                metric.add_metric([], value)
            yield metric
        status = GaugeMetricFamily(
            "load_run_status",
            "RUNNING=1 COOLDOWN=2 DONE=3 FAILED=4",
            labels=["profile"],
        )
        status.add_metric([self.profile.name], self.status)
        yield status
        for name, key in (
            ("pulsepay_container_cpu_percent", "cpu_percent"),
            ("pulsepay_container_memory_bytes", "memory_bytes"),
            ("pulsepay_container_memory_percent", "memory_percent"),
        ):
            metric = GaugeMetricFamily(name, "Docker resource observations", labels=["service"])
            for service, values in self.container_resources.items():
                if (
                    values.get(key) is not None
                    and time.time() - values.get("observed_epoch", 0) < 10
                ):
                    metric.add_metric([service], values[key])
            yield metric
        verdict = GaugeMetricFamily(
            "load_verification_status", "PASS=0 FAIL=1 UNKNOWN=2 DEGRADED=3"
        )
        verdict.add_metric(
            [],
            {"PASS": 0, "FAIL": 1, "UNKNOWN": 2, "DEGRADED": 3}.get(
                self.verification.get("status"), 2
            ),
        )
        yield verdict
        stamp = self.verification.get("finished_at")
        if stamp:
            age = GaugeMetricFamily(
                "load_verification_last_timestamp_seconds",
                "Last independent check timestamp",
            )
            age.add_metric([], datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
            yield age
