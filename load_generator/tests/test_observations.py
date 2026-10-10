from load_generator.controller.observations import required_evidence_healthy
from load_generator.controller.observations import integrity_requires_stop


def test_required_evidence_must_remain_fresh_throughout_measurement():
    good = {
        "phase": "running",
        "prometheus": {
            "gaps": [],
            "values": {
                key: 0
                for key in (
                    "api_http_counter",
                    "db_checked_out",
                    "outbox_pending",
                    "worker_pending",
                    "verifier_status",
                )
            },
        },
    }
    assert required_evidence_healthy([good, good], "HEALTHY")
    assert not required_evidence_healthy(
        [good, good, {"phase": "running", "prometheus": {"gaps": ["scrape:api"]}}],
        "HEALTHY",
    )
    assert not required_evidence_healthy([good, good], "DEGRADED")


def test_operational_lag_is_distinct_from_corruption_and_unknown_evidence():
    assert not integrity_requires_stop(
        {
            "status": "DEGRADED",
            "checks": [
                {"name": "ledger", "status": "PASS"},
                {"name": "event_delivery_lag", "status": "DEGRADED"},
            ],
        }
    )
    assert integrity_requires_stop({"status": "FAIL"})
    assert integrity_requires_stop({"status": "UNKNOWN"})
    assert integrity_requires_stop(
        {"status": "DEGRADED", "checks": [{"status": "FAIL"}]}
    )
