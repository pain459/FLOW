import pytest
from pathlib import Path
from load_generator.tests.test_contracts import profile_values


def test_exclusive_run_lock_releases_after_exit(tmp_path):
    from load_generator.controller.lifecycle import RunLock

    with RunLock(tmp_path):
        with pytest.raises(RuntimeError):
            with RunLock(tmp_path):
                pass
    with RunLock(tmp_path):
        pass


def test_schedule_separates_warmup_burst_and_finite_end():
    from load_generator.controller.schemas import Profile
    from load_generator.workloads.pacing import stage_at

    p = Profile.model_validate(
        {
            **profile_values(),
            "stages": [
                {"seconds": 40, "users": 4},
                {"seconds": 40, "users": 20},
                {"seconds": 40, "users": 4},
            ],
        }
    )
    assert stage_at(p, 10) == ("warmup", 4)
    assert stage_at(p, 31) == ("running", 4)
    assert stage_at(p, 71) == ("running", 20)
    assert stage_at(p, 111) == ("running", 4)
    assert stage_at(p, 150) == ("cooldown", 0)


def test_reports_preserve_unknown_and_exclude_warmup():
    from load_generator.controller.reports import build_summary

    report = build_summary(
        {"run_id": "test", "profile": profile_values()},
        {
            "warmup": {"http": 1000},
            "measured": {
                "http": 100,
                "outcomes": {"success": 100},
                "latencies": {"10": 90, "100": 10},
                "operations": {"balance_read": 100},
            },
        },
        {"status": "PASS"},
        {"status": "UNKNOWN"},
        10,
        [],
    )
    assert report["http"]["completed"] == 100
    assert report["http"]["p50_ms"] == 10 and report["http"]["p99_ms"] == 100
    assert report["load"]["achieved_rps"] == 10
    assert report["integrity"]["postflight"] == "UNKNOWN"
    assert report["result"] == "INCOMPLETE"


def test_absent_measurement_is_not_successful_zero():
    from load_generator.controller.reports import build_summary

    report = build_summary(
        {"run_id": "test", "profile": profile_values()},
        {},
        {"status": "PASS"},
        {"status": "PASS"},
        0,
        [],
    )
    assert report["http"]["p95_ms"] is None
    assert report["load"]["achieved_rps"] is None
    assert report["result"] == "INCOMPLETE"


def test_atomic_json_and_run_path_cannot_escape_reports(tmp_path):
    from load_generator.controller.lifecycle import atomic_json, run_path

    atomic_json(tmp_path / "example.json", {"status": "READY"})
    assert (tmp_path / "example.json").read_text().strip().startswith("{")
    assert run_path(tmp_path, "load-test") == tmp_path / "load-test"
    with pytest.raises(ValueError):
        run_path(tmp_path, "../../etc")
    with pytest.raises(OSError):
        atomic_json(Path("/proc/pulsepay-unwritable.json"), {})


def test_stop_waits_for_supported_finalization_and_never_claims_early_completion(
    tmp_path, monkeypatch
):
    from load_generator.controller import cli
    from load_generator.controller.lifecycle import atomic_json
    from load_generator.controller.schemas import Profile

    profile = Profile.model_validate(
        {**profile_values(), "cooldown_seconds": 180, "reconciliation_seconds": 120}
    )
    path = tmp_path / "load-stop-test"
    path.mkdir()
    atomic_json(tmp_path / "active.json", {"run_id": path.name})
    atomic_json(path / "manifest.json", {"profile": profile.model_dump()})
    clock = [0]

    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= 70:
            atomic_json(path / "summary.json", {"result": "INTERRUPTED"})

    def lock_busy(*args):
        raise RuntimeError("Existing controller owns run")

    monkeypatch.setattr(cli.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cli.time, "sleep", sleep)
    monkeypatch.setattr(cli, "RunLock", lock_busy)
    result = cli.stop_run(tmp_path)
    assert (path / "cancel").exists()
    assert result == {"run_id": path.name, "status": "INTERRUPTED"}
    assert 70 <= clock[0] < 600
