import json
from datetime import datetime, timezone, timedelta
import httpx


def test_missing_or_stale_prometheus_is_unknown_not_zero():
    from load_generator.controller.telemetry import prometheus_sample

    def respond(request):
        if request.url.path.endswith("targets"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "activeTargets": [
                            {
                                "labels": {"job": job},
                                "health": "up",
                                "lastScrape": (
                                    datetime.now(timezone.utc) - timedelta(minutes=2)
                                ).isoformat(),
                            }
                            for job in (
                                "api",
                                "outbox-relay",
                                "event-worker",
                                "verifier",
                            )
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = prometheus_sample(client)
    assert result["values"]["api_rps"] is None
    assert "scrape:api" in result["gaps"]


def test_metadata_never_records_unrequested_secret_fields():
    from load_generator.controller.resources import collect_metadata

    metadata = collect_metadata(
        [
            json.dumps(
                {
                    "service": "api",
                    "image_id": "sha256:example",
                    "cpu_limit": 1000000000,
                    "password": "secret",
                }
            ),
            json.dumps({"docker_cpus": 4, "secret": "secret"}),
        ]
    )
    assert "secret" not in json.dumps(metadata)
    assert metadata["services"]["api"]["cpu_limit"] == 1


def test_baseline_requires_matching_images_and_initial_data_volume():
    from load_generator.controller.baseline import qualify

    manifests = [
        {
            "schema_version": 1,
            "run_id": str(i),
            "git_sha": "revision",
            "profile": {"name": "nominal"},
            "profile_sha256": "profile",
            "source_tree_sha256": "code",
            "dataset_sha256": "dataset",
            "environment": {
                "services": {
                    service: {
                        "image_id": "image",
                        "cpu_limit": 1,
                        "memory_limit_bytes": 123,
                        "config": {
                            key: "value"
                            for key in (
                                "DB_POOL_SIZE",
                                "DB_TIMEOUT_SECONDS",
                                "REQUEST_TIMEOUT_SECONDS",
                                "CACHE_TTL_SECONDS",
                                "PULSEPAY_CURRENCY",
                                "WORKER_POLL_SECONDS",
                                "RECLAIM_IDLE_MS",
                            )
                        },
                    }
                    for service in (
                        "api",
                        "postgres",
                        "redis",
                        "outbox-relay",
                        "event-worker",
                        "load-controller",
                    )
                },
                "machine": {"docker_cpus": 4, "docker_memory_bytes": 1024},
            },
            "snapshot_pre": {
                "totals": {
                    "accounts": 200,
                    "transfers": 0,
                    "ledger_entries": 200,
                    "balance_minor": "20000000",
                    "provisioned_minor": "20000000",
                    "projections": 0,
                }
            },
            "generator_limits": {"cpu_limit": 1, "memory_limit_bytes": 123},
            "traffic_mode": "on_demand",
        }
        for i in range(3)
    ]
    summaries = [
        {
            "run_id": str(i),
            "result": "PASS",
            "generator_saturation_observed": False,
            "load": {"achieved_rps": value},
            "http": {"p50_ms": 10, "p95_ms": 20, "p99_ms": 30},
            "integrity": {"preflight": "PASS", "postflight": "PASS"},
        }
        for i, value in enumerate((10, 11, 9))
    ]
    result = qualify(manifests, summaries)
    assert result["result"] == "PASS"
    assert result["metrics"]["achieved_rps"] == {"median": 10, "min": 9, "max": 11}
    manifests[2]["snapshot_pre"]["totals"]["transfers"] = 1
    assert qualify(manifests, summaries)["result"] == "INCOMPLETE"


def test_resource_metrics_use_service_labels_not_container_ids():
    from load_generator.controller.resources import resource_metric_values

    values = resource_metric_values(
        {
            "name": "chaosloop-postgres-1",
            "cpu_percent": "23.5%",
            "memory_percent": "12.0%",
            "memory": "92MiB / 768MiB",
        }
    )
    assert values["service"] == "postgres"
    assert values["cpu_percent"] == 23.5
    assert values["memory_bytes"] == 92 * 1024**2


def test_baseline_rejects_duplicate_repetitions():
    from load_generator.controller.baseline import qualify

    manifest = {"profile_sha256": "same", "traffic_mode": "on_demand"}
    summary = {
        "run_id": "same-run",
        "result": "PASS",
        "integrity": {"preflight": "PASS", "postflight": "PASS"},
        "load": {"achieved_rps": 10},
        "http": {"p50_ms": 1, "p95_ms": 2, "p99_ms": 3},
    }
    assert qualify([manifest] * 3, [summary] * 3)["result"] == "INCOMPLETE"


def test_controlled_rejection_must_match_expected_code():
    from load_generator.clients.contracts import classify

    assert (
        classify(
            "rejection",
            409,
            {"code": "ACCOUNT_INACTIVE", "message": "inactive", "request_id": "test"},
            {"expected_code": "INVALID_TRANSFER"},
        )
        == "contract_error"
    )
