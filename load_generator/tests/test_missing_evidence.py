from load_generator.controller.baseline import qualify
from load_generator.controller.reports import build_summary


def test_missing_manifests_never_qualify_as_matching_baselines():
    summaries = [
        {
            "run_id": str(i),
            "result": "PASS",
            "integrity": {"preflight": "PASS", "postflight": "PASS"},
            "load": {"achieved_rps": 10},
            "http": {"p50_ms": 1, "p95_ms": 2, "p99_ms": 3},
        }
        for i in range(3)
    ]
    assert qualify([{}, {}, {}], summaries)["result"] == "INCOMPLETE"


def test_missing_worker_measurements_are_unknown_not_zero_failures():
    summary = build_summary(
        {"run_id": "load-test", "profile": {"name": "smoke"}},
        {"measured": {"http": 100}},
        {"status": "PASS"},
        {"status": "PASS"},
        10,
        [],
    )
    assert summary["result"] == "INCOMPLETE"
    assert summary["http"]["failed"] is None


def test_missing_runtime_config_disqualifies_otherwise_complete_provenance():
    from load_generator.controller.baseline import complete_manifest

    manifest = {
        "schema_version": 1,
        "run_id": "test",
        "git_sha": "revision",
        "profile": {"name": "nominal"},
        "profile_sha256": "profile",
        "dataset_sha256": "dataset",
        "source_tree_sha256": "source",
        "traffic_mode": "on_demand",
        "generator_limits": {"cpu_limit": 1, "memory_limit_bytes": 100},
        "environment": {
            "machine": {"docker_cpus": 4, "docker_memory_bytes": 100},
            "services": {
                service: {
                    "image_id": "image",
                    "cpu_limit": 1,
                    "memory_limit_bytes": 100,
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
        },
        "snapshot_pre": {
            "totals": dict.fromkeys(
                (
                    "accounts",
                    "transfers",
                    "ledger_entries",
                    "balance_minor",
                    "provisioned_minor",
                    "projections",
                ),
                0,
            )
        },
    }
    assert not complete_manifest(manifest, {"run_id": "test"})
