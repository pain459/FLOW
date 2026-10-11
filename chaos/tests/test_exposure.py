"""Operator-selected exposure stays bounded from browser to private authority."""

import copy
import io
import hashlib
import json
import sys
import time

import pytest
import yaml

from chaos import authority, cli, gateway, policy, state, watchdog, workbench
from chaos.preflight import validate
from chaos.tests.test_safety_guards import target
from chaos.tests.test_workbench import client, headers


@pytest.mark.parametrize("scenario", policy.SCENARIOS)
def test_native_exposure_override_preserves_committed_definition(scenario):
    source, _, defaults = validate(scenario)
    original = source.read_bytes()
    _, _, selected = validate(scenario, duration_seconds=300)
    assert selected["duration_seconds"] == 300
    assert selected["ttl_seconds"] == 420
    assert source.read_bytes() == original
    assert defaults["duration_seconds"] == policy.SCENARIOS[scenario][2]


@pytest.mark.parametrize("seconds", [True, 3.5, "60", 2, 301])
def test_duration_override_cannot_bypass_policy_types_or_ceiling(seconds):
    with pytest.raises(ValueError):
        policy.bound_configuration("002-worker-pause", {}, duration_seconds=seconds)


def test_long_exposure_remains_exactly_frozen_at_the_docker_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(authority, "AUTHORITY", tmp_path)
    configuration = policy.bound_configuration("002-worker-pause", {}, duration_seconds=60)
    frozen_target = target("event-worker")
    frozen_target["Name"] = "/chaosloop-event-worker-1"
    frozen = authority.freeze(
        {
            "run_id": "chaos-long-test",
            "scenario": "002-worker-pause",
            "target_id": frozen_target["Id"],
            "configuration": configuration,
        },
        "chaosloop",
        frozen_target,
    )
    assert 179 <= frozen["expires_epoch"] - time.time() <= 180
    command = policy.pumba_command(frozen, "chaosloop")
    assert command[command.index("--duration") + 1] == "60s"
    body = {"Image": policy.PUMBA_IMAGE, "Cmd": command, "HostConfig": {}}
    policy.validate_helper(body, frozen, "chaosloop")
    forged = copy.deepcopy(body)
    forged["Cmd"][command.index("--duration") + 1] = "61s"
    with pytest.raises(ValueError, match="exact leased Pumba"):
        policy.validate_helper(forged, frozen, "chaosloop")
    with pytest.raises(ValueError):
        policy.bound_configuration(
            "002-worker-pause", {"duration_seconds": 300, "ttl_seconds": 180}
        )
    with pytest.raises(ValueError):
        policy.bound_configuration(
            "002-worker-pause", {"duration_seconds": 300, "ttl_seconds": 421}
        )


@pytest.mark.parametrize(
    "scenario", ["002-worker-pause", "003-redis-outage", "004-api-network-delay"]
)
def test_targeting_dry_run_does_not_consume_the_selected_fault_lifetime(scenario):
    frozen = {
        "scenario": scenario,
        "target": {"Name": "/exact-lab-target"},
        "configuration": policy.bound_configuration(scenario, {}, duration_seconds=300),
    }
    dry = policy.pumba_command(frozen, "chaosloop", dry=True)
    actual = policy.pumba_command(frozen, "chaosloop")
    assert "--dry-run" in dry
    assert dry[dry.index("--duration") + 1] == "3s"
    assert actual[actual.index("--duration") + 1] == "300s"
    assert dry[-1] == actual[-1] == "exact-lab-target"


@pytest.mark.parametrize("lost_heartbeat", [False, True])
def test_long_fault_watchdog_deadline_stays_finite_and_nonrenewable(
    monkeypatch, tmp_path, lost_heartbeat
):
    clock = {"epoch": 1000.0}
    frozen = {
        "run_id": "chaos-long-watchdog",
        "scenario": "002-worker-pause",
        "configuration": policy.bound_configuration("002-worker-pause", {}, duration_seconds=300),
        "expires_epoch": 1420.0,
        "armed": True,
        "revoked": False,
    }
    monkeypatch.setattr(gateway, "current_lease", lambda: frozen)
    monkeypatch.setattr(gateway, "injection_guard", lambda _: None)
    monkeypatch.setattr(authority, "save", lambda *a: None)
    monkeypatch.setattr(gateway.time, "time", lambda: clock["epoch"])
    gateway.mark_injection()
    assert frozen["fault_deadline_epoch"] == 1315
    clock["epoch"] = 1020
    gateway.mark_injection()
    assert frozen["fault_deadline_epoch"] == 1315
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(state, "heartbeat_epoch", lambda _: clock["epoch"])
    calls = []

    class Docker:
        def lease(self):
            return frozen

        def revoke(self):
            calls.append("revoke")

        def call(self, method, path, **kwargs):
            calls.append(path)

    monkeypatch.setattr(watchdog, "Docker", Docker)
    monkeypatch.setattr(
        watchdog, "restore", lambda _: calls.append("restore") or {"status": "RESTORED"}
    )
    watchdog.tick()
    assert calls == ["/lab/watchdog"]
    calls.clear()
    clock["epoch"] = 1035 if lost_heartbeat else 1315
    if lost_heartbeat:
        monkeypatch.setattr(state, "heartbeat_epoch", lambda _: clock["epoch"] - 13)
    watchdog.tick()
    assert calls == ["revoke", "restore", "/lab/restored"]
    result = state.read(tmp_path / frozen["run_id"] / "watchdog-triggered.json")
    assert result["reason"] == (
        "RUNNER_HEARTBEAT_LOST" if lost_heartbeat else "FAULT_LIFETIME_EXCEEDED"
    )


def test_workbench_catalog_publishes_exposure_limits(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    item = next(
        item
        for item in api.get("/api/scenarios").json()["items"]
        if item["id"] == "002-worker-pause"
    )
    assert item["duration_seconds"] == 20
    assert item["min_duration_seconds"] == 3
    assert item["max_duration_seconds"] == 300


@pytest.mark.parametrize("operation", ["preflight", "run"])
def test_workbench_accepts_selected_duration_before_native_execution(
    tmp_path, monkeypatch, operation
):
    api = client(tmp_path, monkeypatch)
    jobs = api.app.state.jobs
    monkeypatch.setattr(jobs, "execute", lambda record: None)
    response = api.post(
        "/api/actions/" + operation,
        json={
            "scenario": "002-worker-pause",
            "confirm": "002-worker-pause",
            "duration_seconds": 300,
        },
        headers=headers(api),
    )
    assert response.status_code == 202
    assert response.json()["duration_seconds"] == 300
    assert response.json()["ttl_seconds"] == 420
    assert state.active() is None


@pytest.mark.parametrize("seconds", [True, 3.5, "60", 2, 301])
def test_invalid_browser_exposure_starts_no_job(tmp_path, monkeypatch, seconds):
    api = client(tmp_path, monkeypatch)
    response = api.post(
        "/api/actions/preflight",
        json={"scenario": "002-worker-pause", "duration_seconds": seconds},
        headers=headers(api),
    )
    assert response.status_code == 422
    assert api.app.state.jobs.latest is None
    assert state.active() is None


@pytest.mark.parametrize("operation", ["abort", "restore"])
def test_restoration_actions_cannot_accept_duration_arguments(tmp_path, monkeypatch, operation):
    api = client(tmp_path, monkeypatch)
    response = api.post(
        "/api/actions/" + operation, json={"duration_seconds": 60}, headers=headers(api)
    )
    assert response.status_code == 422
    assert api.app.state.jobs.latest is None


def test_browser_subprocess_has_time_for_long_exposure_and_recovery(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    commands, waits = [], []

    class Child:
        returncode = 0
        pid = 999999

        def __init__(self, command, **kwargs):
            commands.append(command)
            self.stdout = io.BytesIO(b'{"result":"PASS"}\n')

        def wait(self, timeout):
            waits.append(timeout)
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(workbench.subprocess, "Popen", Child)
    record = {
        "job_id": "job-test",
        "operation": "run",
        "scenario": "002-worker-pause",
        "status": "RUNNING",
        "duration_seconds": 300,
        "ttl_seconds": 420,
    }
    api.app.state.jobs.execute(record)
    assert commands == [
        [sys.executable, "-m", "chaos.cli", "run", "002-worker-pause", "--duration-seconds", "300"]
    ]
    assert 500 <= waits[0] <= 510
    assert record["status"] == "COMPLETED"


@pytest.mark.parametrize("operation", ["preflight", "run"])
def test_native_cli_forwards_explicit_exposure(monkeypatch, operation):
    calls = []
    monkeypatch.setattr(
        sys, "argv", ["chaos.cli", operation, "002-worker-pause", "--duration-seconds", "60"]
    )
    monkeypatch.setattr(cli, "execution", lambda *a, **kw: calls.append((a, kw)) or 0)
    assert cli.main() == 0
    assert calls == [
        (("002-worker-pause",), {"inject": operation == "run", "duration_seconds": 60})
    ]


def test_native_preflight_persists_effective_exposure_and_hash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(state, "CONTROL", tmp_path / "control")
    state.EVIDENCE.mkdir()
    calls = []

    def preflight(frozen, path):
        assert frozen["configuration"]["duration_seconds"] == 60
        assert frozen["configuration"]["ttl_seconds"] == 180
        frozen["target"] = {"Id": "a" * 64, "Name": "/exact-lab-worker"}

    class Docker:
        def release(self):
            calls.append("release")

    monkeypatch.setattr(cli, "preflight", preflight)
    monkeypatch.setattr(cli, "Docker", Docker)
    assert cli.execution("002-worker-pause", duration_seconds=60) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[-1]["injected"] is False
    assert output[-1]["exposure_seconds"] == 60
    assert output[-1]["ttl_seconds"] == 180
    path = state.EVIDENCE / output[-1]["run_id"]
    effective = (path / "experiment.yaml").read_bytes()
    assert yaml.safe_load(effective)["configuration"]["duration_seconds"] == 60
    assert (
        state.read(path / "metadata.json")["effective_experiment_sha256"]
        == hashlib.sha256(effective).hexdigest()
    )
    assert state.read(path / "summary.json")["exposure_seconds"] == 60
    assert calls == ["release"]


def test_native_cli_rejects_exposure_on_non_experiment_commands(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["chaos.cli", "abort", "--duration-seconds", "60"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code != 0
