import csv
import hashlib
import json
import math
from pathlib import Path
from load_generator.controller.lifecycle import read_json, atomic_json


def merge_workers(path: Path) -> tuple[dict, list[dict]]:
    totals: dict = {}
    workers = []
    for file in sorted((path / "workers").glob("*.json")):
        worker = read_json(file)
        if not worker:
            continue
        workers.append(worker)
        for phase, stats in worker.get("phases", {}).items():
            target = totals.setdefault(phase, {})
            for key, value in stats.items():
                if isinstance(value, dict):
                    dest = target.setdefault(key, {})
                    for label, count in value.items():
                        dest[label] = dest.get(label, 0) + count
                elif isinstance(value, (int, float)):
                    target[key] = target.get(key, 0) + value
    return totals, workers


def percentile(histogram: dict, percent: int) -> float | None:
    count = sum(histogram.values())
    if not count:
        return None
    rank = math.ceil(count * percent / 100)
    for latency, size in sorted(histogram.items(), key=lambda item: int(item[0])):
        rank -= size
        if rank <= 0:
            return float(latency)
    return None


def build_summary(
    manifest: dict,
    stats: dict,
    pre: dict,
    post: dict,
    seconds: float,
    failures: list[str],
    interrupted: bool = False,
    reconciliation: dict | None = None,
) -> dict:
    measured = stats.get("measured", {})
    complete = complete_measurements(measured)
    total = measured.get("http", 0)
    outcomes = measured.get("outcomes", {})
    infrastructure = sum(
        outcomes.get(name, 0) for name in ("infrastructure_failure", "timeout", "contract_error")
    )
    attempted = measured.get("logical_attempts", 0)
    confirmed = measured.get("confirmed_commits", 0)
    rejected = measured.get("logical_rejections", 0)
    unknown = max(measured.get("unknown_outcomes", 0), attempted - confirmed - rejected)
    unknown_initial = unknown
    reconciled = reconciliation.get("phases", {}).get("measured", {}) if reconciliation else {}
    recovered = reconciled.get("reconciled_commits", 0)
    recovered_rejections = max(0, reconciled.get("rejected", 0) - rejected)
    if reconciliation and reconciliation.get("status") == "COMPLETE":
        unknown = max(
            reconciled.get("unresolved", 0),
            attempted - confirmed - rejected - recovered - recovered_rejections,
            unknown_initial - recovered - recovered_rejections,
        )
    intent_gap = bool(
        reconciliation
        and reconciliation.get("status") == "COMPLETE"
        and reconciled.get("intents", 0) != attempted
    )
    result = "PASS"
    if interrupted:
        result = "INTERRUPTED"
    elif (
        post.get("status") == "FAIL"
        or pre.get("status") == "FAIL"
        or failures
        or infrastructure
        or unknown
        or measured.get("unexpected_business_rejections", 0)
        or measured.get("replay_inconsistency", 0)
        or measured.get("intent_storage_failures", 0)
        or (reconciliation and reconciliation.get("status") == "INCONSISTENT")
    ):
        result = "FAILED"
    elif (
        not complete
        or not total
        or seconds <= 0
        or pre.get("status") != "PASS"
        or post.get("status") != "PASS"
        or intent_gap
        or (reconciliation and reconciliation.get("status") != "COMPLETE")
    ):
        result = "INCOMPLETE"
    durations = measured.get("latencies", {})
    return {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "profile": manifest["profile"]["name"],
        "profile_sha256": manifest.get("profile_sha256"),
        "git_sha": manifest.get("git_sha"),
        "environment": manifest.get("environment", {}),
        "timing": {"measured_seconds": seconds},
        "load": {
            "achieved_rps": total / seconds if seconds > 0 and total else None,
            "offered_operations_per_second": measured.get("offered", 0) / seconds
            if seconds > 0 and measured
            else None,
            "target_rps": None,
            "target_operations_per_second": manifest["profile"].get("target_operations_per_second"),
            "configured_users": manifest["profile"].get("users"),
            "mode": "closed_loop",
        },
        "http": {
            "completed": total,
            "failed": infrastructure if complete else None,
            "valid_reads": measured.get("valid_reads", 0),
            "valid_transfer_submissions": measured.get("valid_transfer_submissions", 0),
            "outcomes": outcomes,
            "operations": measured.get("operations", {}),
            "latency_by_operation": {
                operation: {
                    f"p{p}_ms": percentile(
                        {
                            key.split(":", 1)[1]: value
                            for key, value in measured.get("operation_latencies", {}).items()
                            if key.startswith(operation + ":")
                        },
                        p,
                    )
                    for p in (50, 95, 99)
                }
                for operation in measured.get("operations", {})
            },
            "p50_ms": percentile(durations, 50),
            "p95_ms": percentile(durations, 95),
            "p99_ms": percentile(durations, 99),
            "response_bytes": measured.get("response_bytes"),
            "request_body_bytes": measured.get("request_body_bytes"),
        },
        "business": {
            "unique_transfer_attempts": attempted,
            "confirmed_commits": confirmed,
            "duplicate_replays": measured.get("duplicate_replays", 0),
            "business_rejections": rejected,
            "expected_rejections": outcomes.get("expected_rejection", 0),
            "unknown_outcomes": unknown,
            "unknown_outcomes_before_reconciliation": unknown_initial,
            "reconciled_commits": recovered,
            "reconciled_rejections": recovered_rejections,
            "durable_intents": reconciled.get("intents") if reconciliation else None,
        },
        "warmup": stats.get("warmup", {}),
        "integrity": {
            "preflight": pre.get("status", "UNKNOWN"),
            "postflight": post.get("status", "UNKNOWN"),
        },
        "health": {
            "preflight": manifest.get("preflight_health", "UNKNOWN"),
            "postflight": "UNKNOWN",
        },
        "result": result,
        "reconciliation": reconciliation,
        "failures": failures + ([] if complete else ["WORKER_MEASUREMENTS_INCOMPLETE"]),
        "artifact_paths": [
            "manifest.json",
            "summary.json",
            "summary.md",
            "locust-stats.csv",
            "time-series.json",
            "verifier-pre.json",
            "verifier-post.json",
            "errors.jsonl",
            "reconciliation.json",
            "intent-journal/",
            "integrity-observations.jsonl",
        ],
    }


def complete_measurements(measured: dict) -> bool:
    total = measured.get("http")
    if not isinstance(total, int) or total <= 0:
        return False
    for key in ("offered", "response_bytes", "request_body_bytes"):
        value = measured.get(key)
        if not isinstance(value, int) or value < 0:
            return False
    for key in ("outcomes", "operations", "labels", "latencies", "operation_latencies"):
        counts = measured.get(key)
        if (
            not isinstance(counts, dict)
            or any(not isinstance(value, int) or value < 0 for value in counts.values())
            or sum(counts.values()) != total
        ):
            return False
    return measured.get("valid_reads", 0) + measured.get(
        "valid_transfer_submissions", 0
    ) == measured["outcomes"].get("success", 0) + measured["outcomes"].get("replay", 0)


def write_report(path: Path, summary: dict, stats: dict, samples: list, workers: list[dict]):
    atomic_json(path / "summary.json", summary)
    atomic_json(path / "time-series.json", {"schema_version": 1, "samples": samples})
    lines = [
        f"# PulsePay workload {summary['run_id']}",
        "",
        f"Result: **{summary['result']}**; profile `{summary['profile']}`.",
        f"Integrity pre/post: {summary['integrity']['preflight']} / {summary['integrity']['postflight']}.",
        f"Measured seconds: {summary['timing']['measured_seconds']:.3f}; achieved HTTP RPS: {summary['load']['achieved_rps']}.",
        f"HTTP p50/p95/p99 ms: {summary['http']['p50_ms']} / {summary['http']['p95_ms']} / {summary['http']['p99_ms']}.",
        f"Confirmed logical commits: {summary['business']['confirmed_commits']}; unknown: {summary['business']['unknown_outcomes']}.",
        f"Commits reconciled after traffic: {summary['business'].get('reconciled_commits', 0)}; excluded from measured throughput.",
        "",
        "Warmup is excluded. Closed-loop operation ceiling is not an arrival guarantee. See manifest and underlying samples.",
        "",
        "Failures: " + (", ".join(summary["failures"]) or "none"),
    ]
    (path / "summary.md").write_text("\n".join(lines) + "\n")
    with (path / "locust-stats.csv").open("w") as file:
        writer = csv.writer(file)
        writer.writerow(["operation", "measured_http_requests", "p50_ms", "p95_ms", "p99_ms"])
        measured = stats.get("measured", {})
        for operation, count in measured.get("operations", {}).items():
            histogram = {
                key.split(":", 1)[1]: value
                for key, value in measured.get("operation_latencies", {}).items()
                if key.startswith(operation + ":")
            }
            writer.writerow([operation, count, *[percentile(histogram, p) for p in (50, 95, 99)]])
    with (path / "errors.jsonl").open("w") as file:
        for worker in workers:
            for error in worker.get("errors", [])[:50]:
                file.write(json.dumps(error) + "\n")


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
