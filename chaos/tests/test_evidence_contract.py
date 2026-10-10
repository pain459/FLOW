from chaos.adapters import evidence, injection, observations
from chaos import state
import pytest


def journal():
    return {
        "status": "completed",
        "deviated": False,
        "steady_states": {
            "before": {"steady_state_met": True},
            "after": {"steady_state_met": True},
        },
        "run": [
            {"status": "succeeded", "activity": {"name": name}, "output": True}
            for name in (
                "apply-bounded-framework-fault",
                "observe-intentional-fault-exposure",
                "restore-original-environment",
                "independently-verify-post-restoration-recovery",
            )
        ],
        "rollbacks": [
            {
                "status": "succeeded",
                "activity": {"name": "repeat-safe-scoped-restoration"},
            }
        ],
    }


def verdict(value=None, **kwargs):
    return evidence.verdict(
        value or journal(),
        {"status": "PASS"},
        {"status": "PASS"},
        {"status": "RESTORED"},
        {"observed": True},
        {"status": "PASS"},
        **kwargs,
    )


def test_failed_native_activity_cannot_pass_despite_completed_journal():
    value = journal()
    value["run"][0]["status"] = "failed"
    assert verdict(value) != "PASS"
    value = journal()
    value["steady_states"]["after"]["steady_state_met"] = False
    assert verdict(value) != "PASS"


def test_stopped_or_unknown_load_cannot_claim_recovery_under_load():
    assert verdict(load_sustained=False) != "PASS"
    assert verdict(load_sustained=True) == "PASS"


def test_fresh_but_stalled_workload_cannot_establish_productive_recovery(monkeypatch, tmp_path):
    import time

    root = tmp_path
    run_id = "load-test"
    monkeypatch.setattr(evidence, "LOAD_REPORTS", root)
    state.write(root / "active.json", {"run_id": run_id})
    state.write(root / run_id / "state.json", {"status": "RUNNING"})
    sample = {
        "epoch": time.time(),
        "phase": "running",
        "active_users": 20,
        "load": {"measured": {"http": 1000, "confirmed_commits": 100}},
    }
    state.write(root / run_id / "latest-observation.json", sample)
    state.write(
        root / run_id / "time-series.json", {"samples": [sample | {"epoch": sample["epoch"] - 20}]}
    )
    assert evidence.active_load(run_id)
    assert not evidence.sustained_load(run_id)
    sample["load"]["measured"].update(http=1200, confirmed_commits=180)
    state.write(root / run_id / "latest-observation.json", sample)
    assert evidence.sustained_load(run_id)


def test_unsuccessful_injector_is_inconclusive_even_with_completed_journal():
    assert verdict(injection_confirmed=False) == "INCONCLUSIVE"


def test_missing_injector_state_is_unknown_and_failed_apply_cannot_confirm(tmp_path):
    result = injection.record_injector_result(None, None, tmp_path)
    assert result["exit_code"] is None
    value = journal()
    value["run"][0]["status"] = "failed"
    assert not evidence.injection_confirmed(value, {"exit_code": 0})


def test_missing_cpu_sample_is_unknown_not_exception():
    assert not injection.expected_impact(
        {"scenario": "006-cpu-pressure"}, {}, {}, {}, {"cpu_utilization": None}
    )


def test_network_latency_uses_http_histogram_when_health_probe_times_out():
    before = {
        "health": {"status": "HEALTHY"},
        "health_request_latency_ms": 5,
        "metrics": {"values": {"api_p95_seconds": 0.05}},
    }
    during = {
        "health": None,
        "health_request_latency_ms": None,
        "metrics": {"values": {"api_p95_seconds": 3.6}},
    }
    assert injection.expected_impact({"scenario": "004-api-network-delay"}, during, before, {})


def test_snapshot_has_no_privileged_fault_truth():
    sample = {
        "observed_at": "2026-10-10T00:00:00Z",
        "window_seconds": 30,
        "metrics": {"values": {}, "gaps": ["db_connections"]},
        "scenario": "001-api-pause",
        "target": "private",
        "injector": "pumba",
        "expected_root_cause": "pause",
    }
    value = observations.snapshot(sample, "chaos-example")
    assert not {"scenario", "target", "injector", "expected_root_cause"} & set(value)
    assert value["api"]["rps"] is None
    assert value["integrity"]["status"] == "UNKNOWN"


def test_interrupted_observer_keeps_collected_metric_evidence(monkeypatch, tmp_path):
    lease = {
        "run_id": "chaos-partial",
        "scenario": "002-worker-pause",
        "configuration": {"duration_seconds": 3},
        "target": {"Id": "a" * 64},
    }
    monkeypatch.setattr(state, "active", lambda: lease)
    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(state, "CONTROL", tmp_path / "control")
    path = state.EVIDENCE / lease["run_id"]
    state.write(path / "baseline.json", {"totals": {"transfers": 100, "projections": 100}})
    sample = {
        "observed_at": state.now(),
        "window_seconds": 30,
        "metrics": {"values": {}, "gaps": []},
        "totals": {"transfers": 120, "projections": 100},
    }
    calls = []

    def capture():
        if calls:
            raise RuntimeError("simulated interrupted observation")
        calls.append(True)
        return sample

    class Docker:
        def inspect(self, identifier):
            return {"Id": identifier, "State": {"Paused": True}}

        def call(self, *args):
            return {}

    monkeypatch.setattr(injection, "Docker", Docker)
    monkeypatch.setattr(observations, "capture", capture)
    monkeypatch.setattr(injection.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="interrupted observation"):
        injection.observe()
    retained = state.read(path / "metrics-during.json")
    assert retained and len(retained) == 1
    assert retained[0]["totals"]["transfers"] == 120
