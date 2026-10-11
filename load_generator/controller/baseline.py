import statistics
from load_generator.controller.reports import fingerprint


def comparable_key(manifest: dict) -> str:
    totals = manifest.get("snapshot_pre", {}).get("totals", {})
    volumes = {
        key: totals.get(key)
        for key in (
            "accounts",
            "transfers",
            "ledger_entries",
            "balance_minor",
            "provisioned_minor",
            "projections",
        )
    }
    environment = manifest.get("environment", {})
    services = {
        name: {
            key: value.get(key) for key in ("image_id", "cpu_limit", "memory_limit_bytes", "config")
        }
        for name, value in environment.get("services", {}).items()
    }
    return fingerprint(
        {
            "profile": manifest.get("profile_sha256"),
            "dataset": manifest.get("dataset_sha256"),
            "source": manifest.get("source_tree_sha256"),
            "images_limits": services,
            "machine": environment.get("machine"),
            "generator": {
                key: manifest.get("generator_limits", {}).get(key)
                for key in ("cpu_limit", "memory_limit_bytes")
            },
            "initial_volume": volumes,
            "traffic_mode": manifest.get("traffic_mode"),
        }
    )


def qualify(manifests: list[dict], summaries: list[dict]) -> dict:
    reasons = []
    if len(manifests) < 3 or len(manifests) != len(summaries):
        reasons.append("AT_LEAST_THREE_COMPLETE_REPETITIONS_REQUIRED")
    if len({summary.get("run_id") for summary in summaries}) != len(summaries):
        reasons.append("DISTINCT_RUN_IDS_REQUIRED")
    provenance_ok = all(
        complete_manifest(manifest, summary) for manifest, summary in zip(manifests, summaries)
    ) and bool(manifests)
    if not provenance_ok:
        reasons.append("MISSING_OR_MISMATCHED_RUN_PROVENANCE")
    if len({comparable_key(manifest) for manifest in manifests}) != 1:
        reasons.append("PROFILE_ENVIRONMENT_OR_INITIAL_DATA_VOLUME_DIFFER")
    for summary in summaries:
        if summary.get("result") != "PASS" or summary.get("generator_saturation_observed"):
            reasons.append("RUN_FAILED_INCOMPLETE_OR_GENERATOR_SATURATED")
        if any(
            summary.get("integrity", {}).get(phase) != "PASS"
            for phase in ("preflight", "postflight")
        ):
            reasons.append("INTEGRITY_NOT_PASS")
    metrics: dict[str, dict | None] = {}
    for name, group in (
        ("achieved_rps", "load"),
        ("p50_ms", "http"),
        ("p95_ms", "http"),
        ("p99_ms", "http"),
    ):
        values = [summary.get(group, {}).get(name) for summary in summaries]
        if any(value is None for value in values) or not values:
            reasons.append("MISSING_MEASUREMENT:" + name)
            metrics[name] = None
        else:
            metrics[name] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
    return {
        "schema_version": 1,
        "result": "INCOMPLETE" if reasons else "PASS",
        "comparison_key": comparable_key(manifests[0]) if provenance_ok else None,
        "run_ids": [summary.get("run_id") for summary in summaries],
        "metrics": metrics,
        "reasons": sorted(set(reasons)),
        "method": "median and range; identical initial dataset/image/profile/limits; no universal RPS gate",
    }


def complete_manifest(manifest: dict, summary: dict) -> bool:
    """Missing provenance cannot establish that repetitions are comparable."""
    if manifest.get("schema_version") != 1 or not manifest.get("run_id"):
        return False
    if manifest["run_id"] != summary.get("run_id"):
        return False
    if not all(
        manifest.get(key)
        for key in ("git_sha", "profile_sha256", "dataset_sha256", "source_tree_sha256")
    ):
        return False
    if not manifest.get("profile", {}).get("name"):
        return False
    totals = manifest.get("snapshot_pre", {}).get("totals", {})
    if any(
        totals.get(key) is None
        for key in (
            "accounts",
            "transfers",
            "ledger_entries",
            "balance_minor",
            "provisioned_minor",
            "projections",
        )
    ):
        return False
    environment = manifest.get("environment", {})
    machine = environment.get("machine", {})
    if not machine.get("docker_cpus") or not machine.get("docker_memory_bytes"):
        return False
    services = environment.get("services", {})
    for service in ("api", "postgres", "redis", "outbox-relay", "event-worker"):
        value = services.get(service, {})
        if not all(value.get(key) for key in ("image_id", "cpu_limit", "memory_limit_bytes")):
            return False
    if not services.get("load-controller", {}).get("image_id"):
        return False
    required_settings = {
        "api": (
            "DB_POOL_SIZE",
            "DB_TIMEOUT_SECONDS",
            "REQUEST_TIMEOUT_SECONDS",
            "CACHE_TTL_SECONDS",
            "PULSEPAY_CURRENCY",
        ),
        "outbox-relay": ("DB_POOL_SIZE", "DB_TIMEOUT_SECONDS", "WORKER_POLL_SECONDS"),
        "event-worker": (
            "DB_POOL_SIZE",
            "DB_TIMEOUT_SECONDS",
            "WORKER_POLL_SECONDS",
            "RECLAIM_IDLE_MS",
        ),
    }
    for service, keys in required_settings.items():
        config = services.get(service, {}).get("config")
        if not isinstance(config, dict) or any(config.get(key) is None for key in keys):
            return False
    limits = manifest.get("generator_limits", {})
    return bool(limits.get("cpu_limit") and limits.get("memory_limit_bytes")) and (
        manifest.get("traffic_mode") == "on_demand"
    )
