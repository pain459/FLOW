"""Pure observation schema and units. No fault definitions or runtime authority."""

import math
import re
from datetime import datetime, timezone

SCHEMA_VERSION = "1.1"
INVESTIGATIONS = [
    "inspect_api",
    "inspect_database",
    "inspect_redis",
    "inspect_workers",
    "collect_more_evidence",
    "escalate",
]
RUN_PATTERN = re.compile(r"chaos-[A-Za-z0-9_-]{1,80}\Z")
MAX_BYTES = 4 * 1024 * 1024
MAX_SAMPLES = 512


def valid_run_id(value):
    return isinstance(value, str) and RUN_PATTERN.fullmatch(value) is not None


def epoch(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def freshness(stamp, observed_at, source, max_age=15, healthy=True):
    now, then = epoch(observed_at), epoch(stamp)
    age = now - then if now is not None and then is not None else None
    status = (
        "UNKNOWN"
        if age is None or age < 0 or not healthy
        else "FRESH"
        if age <= max_age
        else "STALE"
    )
    return {
        "source": source,
        "observed_at": stamp if then is not None else None,
        "age_seconds": age if age is not None and age >= 0 else None,
        "max_age_seconds": max_age,
        "status": status,
    }


def build_snapshot(sample, run_id, integrity=None):
    metrics = sample.get("metrics") or {}
    values, scrapes = metrics.get("values", {}), metrics.get("scrapes", {})
    observed_at = sample["observed_at"]
    sources = {}
    for job in ("api", "db-observer", "event-worker", "outbox-relay", "verifier"):
        scrape = scrapes.get(job, {})
        sources[job] = freshness(
            scrape.get("last_scrape"),
            observed_at,
            "Prometheus scrape",
            healthy=scrape.get("health") == "up",
        )
    for job, metric in (
        ("db-observer", "db_observed_at"),
        ("event-worker", "worker_observed_at"),
        ("outbox-relay", "relay_observed_at"),
    ):
        producer = values.get(metric)
        scrape_quality = sources[job]
        valid = (
            not isinstance(producer, bool)
            and isinstance(producer, (int, float))
            and math.isfinite(producer)
            and 0 < producer <= epoch(observed_at)
            and scrape_quality["age_seconds"] is not None
        )
        # The older of the scrape and producer timestamps bounds evidence age.
        stamp = (
            datetime.fromtimestamp(
                min(producer, epoch(scrape_quality["observed_at"])), timezone.utc
            ).isoformat()
            if valid
            else None
        )
        sources[job] = freshness(
            stamp,
            observed_at,
            "Prometheus producer sample",
            healthy=scrape_quality["status"] != "UNKNOWN",
        )
    load_job = metrics.get("active_load_job")
    if load_job not in ("load", "locust"):
        load_job = "locust" if "locust" in scrapes and "load" not in scrapes else "load"
    load_scrape = scrapes.get(load_job, {})
    sources["load"] = freshness(
        load_scrape.get("last_scrape"),
        observed_at,
        "Prometheus scrape",
        healthy=load_scrape.get("health") == "up",
    )
    sources["dependencies"] = freshness(
        sample.get("health_observed_at", observed_at if sample.get("health") else None),
        observed_at,
        "HTTP dependency probe",
    )
    integrity = integrity or {}
    sources["integrity"] = freshness(
        integrity.get("finished_at"), observed_at, "Independent read-only verifier", max_age=60
    )
    missing = set()

    def number(name, source, field):
        value = values.get(name)
        if (
            sources[source]["status"] != "FRESH"
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            missing.add(field)
            return None
        return value

    def reachable(name):
        status = (
            ((sample.get("health") or {}).get("dependencies") or {}).get(name, {}).get("status")
        )
        if sources["dependencies"]["status"] != "FRESH":
            status = None
        result = True if status == "HEALTHY" else False if status == "UNHEALTHY" else None
        if result is None:
            missing.add("database.reachable" if name == "postgres" else "redis.reachable")
        return result

    rps = number("api_rps", "api", "api.rps")
    errors = number("api_5xx_rate", "api", "api.error_rate_pct")
    error_pct = errors / rps * 100 if errors is not None and rps else None
    if error_pct is None:
        missing.add("api.error_rate_pct")
    api = {"rps": rps, "error_rate_pct": error_pct}
    for quantile in (50, 95, 99):
        name = f"p{quantile}_ms"
        value = number(f"api_p{quantile}_seconds", "api", "api." + name)
        api[name] = value * 1000 if value is not None else None
    worker = {}
    for field, metric, job in (
        ("outbox_pending", "outbox_pending", "outbox-relay"),
        ("outbox_oldest_seconds", "outbox_oldest_seconds", "outbox-relay"),
        ("consumer_lag_messages", "worker_lag", "event-worker"),
        ("pending_messages", "worker_pending", "event-worker"),
        ("oldest_pending_age_seconds", "consumer_oldest_seconds", "event-worker"),
    ):
        worker[field] = number(metric, job, "worker." + field)
    # XINFO GROUPS lag is a COUNT; XPENDING idle age is not end-to-end delay.
    # No current gauge measures the age of every undelivered stream entry.
    worker["consumer_lag_seconds"] = None
    missing.add("worker.consumer_lag_seconds")
    last_status = integrity.get("status", "UNKNOWN")
    if last_status not in ("PASS", "FAIL", "UNKNOWN", "DEGRADED"):
        last_status = "UNKNOWN"
    current_status = last_status if sources["integrity"]["status"] == "FRESH" else "UNKNOWN"
    if current_status == "UNKNOWN":
        missing.add("integrity.status")
    ages = [row["age_seconds"] for row in sources.values() if row["age_seconds"] is not None]
    result = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "observation_time": observed_at,
        "window_seconds": sample["window_seconds"],
        "system": "pulsepay",
        "api": api,
        "database": {
            "reachable": reachable("postgres"),
            "connection_usage_pct": number(
                "db_connection_usage_percent", "db-observer", "database.connection_usage_pct"
            ),
            "lock_waits": number("db_lock_waits", "db-observer", "database.lock_waits"),
            "deadlocks": number("db_deadlocks", "db-observer", "database.deadlocks"),
        },
        "redis": {"reachable": reachable("redis")},
        "worker": worker,
        "integrity": {
            "status": current_status,
            "last_observed_status": last_status,
            "verified_at": sources["integrity"]["observed_at"],
        },
        "load": {
            "rps": number("load_rps", "load", "load.rps"),
            "active_users": number("load_users", "load", "load.active_users"),
            "configured_users": number("load_target_users", "load", "load.configured_users"),
        },
        "freshness": {"sources": sources, "max_signal_age_seconds": max(ages) if ages else None},
        "available_investigations": INVESTIGATIONS.copy(),
    }
    # Only controlled signal identifiers are exported; never raw exception text,
    # arbitrary labels, scenario IDs or collector metadata.
    result["missing_observations"] = sorted(missing)
    result["data_quality"] = "PARTIAL" if missing else "COMPLETE"
    return result


def validate_snapshot(value, run_id=None):
    """Fail closed on unexpected fields anywhere in the public document."""
    sections = {
        "api": {"rps", "error_rate_pct", "p50_ms", "p95_ms", "p99_ms"},
        "database": {"reachable", "connection_usage_pct", "lock_waits", "deadlocks"},
        "redis": {"reachable"},
        "worker": {
            "outbox_pending",
            "outbox_oldest_seconds",
            "consumer_lag_messages",
            "pending_messages",
            "oldest_pending_age_seconds",
            "consumer_lag_seconds",
        },
        "load": {"rps", "active_users", "configured_users"},
        "integrity": {"status", "last_observed_status", "verified_at"},
        "freshness": {"sources", "max_signal_age_seconds"},
    }
    top = set(sections) | {
        "schema_version",
        "run_id",
        "observation_time",
        "window_seconds",
        "system",
        "missing_observations",
        "available_investigations",
        "data_quality",
    }
    if not isinstance(value, dict) or set(value) != top:
        raise ValueError("Unexpected observation fields")
    if (
        value["schema_version"] != SCHEMA_VERSION
        or value["system"] != "pulsepay"
        or not valid_run_id(value["run_id"])
        or run_id not in (None, value["run_id"])
        or epoch(value["observation_time"]) is None
        or type(value["window_seconds"]) is not int
        or not 1 <= value["window_seconds"] <= 300
        or value["available_investigations"] != INVESTIGATIONS
        or value["data_quality"] not in ("PARTIAL", "COMPLETE")
    ):
        raise ValueError("Invalid observation contract")
    missing_fields = set()
    for section, fields in sections.items():
        row = value[section]
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Unexpected observation fields")
        for field, item in row.items():
            missing_fields.add(section + "." + field)
            if section in ("integrity", "freshness"):
                continue
            if field == "reachable":
                if item is not None and type(item) is not bool:
                    raise ValueError("Invalid reachability")
            elif item is not None and (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
                or item < 0
            ):
                raise ValueError("Invalid numeric observation")
    integrity = value["integrity"]
    for field in ("status", "last_observed_status"):
        if integrity[field] not in ("PASS", "FAIL", "UNKNOWN", "DEGRADED"):
            raise ValueError("Invalid integrity status")
    if integrity["verified_at"] is not None and epoch(integrity["verified_at"]) is None:
        raise ValueError("Invalid verifier timestamp")
    sources = value["freshness"]["sources"]
    if not isinstance(sources, dict) or set(sources) != {
        "api",
        "db-observer",
        "event-worker",
        "outbox-relay",
        "verifier",
        "load",
        "dependencies",
        "integrity",
    }:
        raise ValueError("Unexpected observation sources")
    for row in sources.values():
        if not isinstance(row, dict) or set(row) != {
            "source",
            "observed_at",
            "age_seconds",
            "max_age_seconds",
            "status",
        }:
            raise ValueError("Unexpected source fields")
        if (
            row["source"]
            not in (
                "Prometheus scrape",
                "Prometheus producer sample",
                "HTTP dependency probe",
                "Independent read-only verifier",
            )
            or row["status"] not in ("FRESH", "STALE", "UNKNOWN")
            or row["max_age_seconds"] not in (15, 60)
            or row["observed_at"] is not None
            and epoch(row["observed_at"]) is None
        ):
            raise ValueError("Invalid source quality")
        age = row["age_seconds"]
        if age is not None and (
            isinstance(age, bool)
            or not isinstance(age, (int, float))
            or not math.isfinite(age)
            or age < 0
        ):
            raise ValueError("Invalid source age")
        expected_age = (
            epoch(value["observation_time"]) - epoch(row["observed_at"])
            if row["observed_at"] is not None
            else None
        )
        if expected_age is not None and expected_age < 0:
            expected_age = None
        if (
            (age is None) != (expected_age is None)
            or age is not None
            and expected_age is not None
            and not math.isclose(age, expected_age, abs_tol=0.00001)
        ):
            raise ValueError("Contradictory source age")
        if row["status"] == "FRESH" and (age is None or age > row["max_age_seconds"]):
            raise ValueError("Contradictory freshness")
        if row["status"] == "STALE" and (age is None or age <= row["max_age_seconds"]):
            raise ValueError("Contradictory staleness")
    age = value["freshness"]["max_signal_age_seconds"]
    if age is not None and (
        isinstance(age, bool)
        or not isinstance(age, (int, float))
        or not math.isfinite(age)
        or age < 0
    ):
        raise ValueError("Invalid source age")
    if not isinstance(value["missing_observations"], list) or any(
        not isinstance(name, str) or name not in missing_fields
        for name in value["missing_observations"]
    ):
        raise ValueError("Invalid missing observation names")
    expected_missing = set()
    for section in ("api", "database", "redis", "worker", "load"):
        for field, item in value[section].items():
            source = (
                "dependencies"
                if field == "reachable"
                else "db-observer"
                if section == "database"
                else "outbox-relay"
                if field in ("outbox_pending", "outbox_oldest_seconds")
                else "event-worker"
                if section == "worker"
                else section
            )
            if item is None:
                expected_missing.add(section + "." + field)
            elif sources[source]["status"] != "FRESH":
                raise ValueError("Value without fresh provenance")
    expected_integrity = (
        integrity["last_observed_status"]
        if sources["integrity"]["status"] == "FRESH"
        else "UNKNOWN"
    )
    if (
        integrity["status"] != expected_integrity
        or integrity["verified_at"] != sources["integrity"]["observed_at"]
    ):
        raise ValueError("Contradictory integrity evidence")
    if integrity["status"] == "UNKNOWN":
        expected_missing.add("integrity.status")
    if value["missing_observations"] != sorted(expected_missing) or value["data_quality"] != (
        "PARTIAL" if expected_missing else "COMPLETE"
    ):
        raise ValueError("Contradictory data quality")
    source_ages = [row["age_seconds"] for row in sources.values() if row["age_seconds"] is not None]
    expected_max = max(source_ages) if source_ages else None
    if age != expected_max:
        raise ValueError("Contradictory maximum age")
    return value
