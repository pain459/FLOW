import json
import time

import pytest

from chaos import preflight, state


def test_idle_load_reports_how_to_start_locust(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "LOAD_REPORTS", tmp_path)
    value = preflight.workload_status()
    assert value["ready"] is False
    assert value["code"] == "LOAD_NOT_ACTIVE"
    assert "Start" in value["remediation"] and "8089" in value["remediation"]
    with pytest.raises(ValueError, match="active steady HTTP load") as error:
        preflight.load_evidence()
    assert error.value.code == "LOAD_NOT_ACTIVE"


def test_warmup_then_productive_load_uses_the_existing_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "LOAD_REPORTS", tmp_path)
    path = tmp_path / "load-test"
    path.mkdir()
    state.write(tmp_path / "active.json", {"run_id": path.name})
    state.write(path / "state.json", {"status": "WARMUP"})
    now = time.time()
    state.write(path / "latest-observation.json", {"epoch": now, "active_users": 5})
    assert preflight.workload_status()["code"] == "LOAD_WARMING_UP"
    state.write(path / "state.json", {"status": "RUNNING"})
    measured = {"http": 150, "confirmed_commits": 40, "outcomes": {}}
    state.write(
        path / "latest-observation.json",
        {"epoch": now, "active_users": 5, "load": {"measured": measured}},
    )
    assert preflight.workload_status()["code"] == "LOAD_STABILITY_WINDOW_REQUIRED"
    state.write(
        path / "recent-observations.json",
        {
            "samples": [
                {
                    "epoch": now - 20,
                    "phase": "running",
                    "load": {"measured": {"http": 100, "confirmed_commits": 20}},
                }
            ]
        },
    )
    assert preflight.workload_status()["ready"] is True
    assert preflight.workload_status()["run_id"] == path.name
    assert preflight.load_evidence()["run_id"] == path.name
    measured["outcomes"]["timeout"] = 1
    state.write(
        path / "latest-observation.json",
        {"epoch": now, "active_users": 5, "load": {"measured": measured}},
    )
    assert preflight.workload_status()["code"] == "LOAD_BASELINE_ERRORS"


def test_cli_invalid_summary_preserves_safe_gate_reason(tmp_path, monkeypatch, capsys):
    from chaos import cli

    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(state, "CONTROL", tmp_path / "control")
    state.EVIDENCE.mkdir()
    state.CONTROL.mkdir()
    source = tmp_path / "experiment.yaml"
    source.write_text("version: 1.0.0\n")
    monkeypatch.setattr(cli, "validate", lambda *a, **k: (source, {}, {"ttl_seconds": 120}))
    monkeypatch.setattr(preflight, "LOAD_REPORTS", tmp_path / "empty-load")
    monkeypatch.setattr(cli, "preflight", lambda *a: preflight.load_evidence())

    class Docker:
        def lease(self):
            return None

    monkeypatch.setattr(cli, "Docker", Docker)
    assert cli.execution("002-worker-pause") == 1
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "INVALID"
    assert result["code"] == "LOAD_NOT_ACTIVE"
    assert result["message"] == "Scenario requires existing active steady HTTP load"
    assert "8089" in result["remediation"]
    assert state.active() is None


def test_workbench_status_exposes_read_only_workload_prerequisite(tmp_path, monkeypatch):
    from chaos.tests.test_workbench import client

    monkeypatch.setattr(preflight, "LOAD_REPORTS", tmp_path / "empty-load")
    api = client(tmp_path, monkeypatch)
    result = api.get("/api/status").json()
    assert result["workload"]["code"] == "LOAD_NOT_ACTIVE"
    assert result["workload"]["ready"] is False
    assert state.active() is None
