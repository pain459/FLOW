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
    assert integrity_requires_stop({"status": "DEGRADED", "checks": [{"status": "FAIL"}]})


def test_integrity_unknown_grace_is_explicit_bounded_and_fail_never_waits():
    from load_generator.controller.observations import IntegrityGuard

    default = IntegrityGuard()
    assert default.update({"status": "UNKNOWN"}, epoch=10) is True
    guard = IntegrityGuard(unknown_grace_seconds=20)
    assert guard.update({"status": "UNKNOWN"}, epoch=10) is False
    assert guard.expired(epoch=29) is False
    assert guard.expired(epoch=30) is True
    assert guard.update({"status": "PASS", "checks": []}, epoch=31) is True
    assert guard.expired(epoch=50) is True
    assert guard.update({"status": "FAIL"}, epoch=51) is True
    guard = IntegrityGuard(unknown_grace_seconds=20)
    assert guard.update({"status": "DEGRADED", "checks": [{"status": "FAIL"}]}, epoch=10) is True
    assert guard.update({"status": "PASS"}, epoch=11) is True
    recovered = IntegrityGuard(unknown_grace_seconds=20)
    assert recovered.update({"status": "UNKNOWN"}, epoch=10) is False
    assert recovered.update({"status": "PASS"}, epoch=25) is False
    assert recovered.expired(epoch=50) is False


def test_uncertainty_deadline_stops_while_verifier_communication_is_blocked():
    import threading
    from load_generator.controller.observations import IntegrityGuard, watch_integrity_deadline

    guard = IntegrityGuard(unknown_grace_seconds=0.1)
    done, stopped = threading.Event(), threading.Event()
    guard.update({"status": "UNKNOWN"})
    watcher = threading.Thread(
        target=watch_integrity_deadline, args=(guard, done, stopped.set), kwargs={"interval": 0.01}
    )
    watcher.start()
    try:
        # The caller is still awaiting the verifier; a separate clock must stop traffic.
        assert stopped.wait(0.5)
        assert guard.update({"status": "PASS"}) is True
    finally:
        done.set()
        watcher.join(1)
    assert not watcher.is_alive()


def test_manual_locust_deadline_runs_independently_of_verifier_greenlet():
    import gevent
    from gevent.event import Event
    from load_generator.controller.observations import IntegrityGuard, watch_integrity_deadline

    guard = IntegrityGuard(unknown_grace_seconds=0.1)
    done, stopped = Event(), Event()
    guard.update({"status": "UNKNOWN"})
    verifier = gevent.spawn(gevent.sleep, 1)
    watcher = gevent.spawn(watch_integrity_deadline, guard, done, stopped.set, interval=0.01)
    try:
        assert stopped.wait(timeout=0.5)
        assert not verifier.ready()
    finally:
        done.set()
        watcher.join(timeout=1)
        verifier.kill()


def test_recovery_profile_preserves_default_guard_and_limits():
    from load_generator.controller.schemas import load_profile

    assert load_profile("nominal").safety.integrity_unknown_grace_seconds == 0
    recovery = load_profile("dependency_recovery")
    assert recovery.safety.integrity_unknown_grace_seconds == 20
    assert recovery.safety.stop_on_sustained_error_rate_pct == 30
    assert recovery.safety.stop_on_error_window_seconds == 60
    assert recovery.users <= 20 and recovery.duration_seconds <= 600
