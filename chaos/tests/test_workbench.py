import time
from fastapi.testclient import TestClient
from chaos import state


def client(tmp_path, monkeypatch):
    from chaos.workbench import create_app

    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(state, "CONTROL", tmp_path / "control")
    state.EVIDENCE.mkdir()
    return TestClient(create_app(), base_url="http://localhost:8090")


def headers(api):
    return {
        "Origin": "http://localhost:8090",
        "X-CSRF-Token": api.get("/api/session").json()["token"],
    }


def test_local_ui_and_catalog_never_launch_an_experiment(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    assert api.get("/").status_code == 200
    values = api.get("/api/scenarios").json()["items"]
    assert len(values) == 8
    assert next(v for v in values if v["id"] == "006-cpu-pressure")["enabled"] is False
    assert not (state.CONTROL / "active.json").exists()
    assert api.get("/api/scenarios", headers={"Host": "attacker.example:8090"}).status_code == 403


def test_browser_mutations_require_origin_session_and_csrf(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    body = {"scenario": "002-worker-pause"}
    assert api.post("/api/actions/preflight", json=body).status_code == 403
    assert (
        api.post(
            "/api/actions/preflight", json=body, headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    token = headers(api)
    token["Origin"] = "http://127.0.0.1:8090"
    assert api.post("/api/actions/preflight", json=body, headers=token).status_code == 403


def test_unsupported_actions_targets_and_unconfirmed_runs_fail_closed(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    token = headers(api)
    for body in (
        {"scenario": "re2:.*"},
        {"scenario": "002-worker-pause", "command": "sh"},
        {"scenario": "006-cpu-pressure"},
    ):
        assert api.post("/api/actions/run", json=body, headers=token).status_code in {409, 422}
    assert (
        api.post(
            "/api/actions/run", json={"scenario": "002-worker-pause"}, headers=token
        ).status_code
        == 422
    )
    assert api.post("/api/actions/shell", json={}, headers=token).status_code == 404


def test_history_exposes_actual_failure_and_bounded_evidence(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    identifier = "chaos-test-failure"
    path = state.EVIDENCE / identifier
    path.mkdir()
    state.write(
        path / "summary.json",
        {"run_id": identifier, "result": "RESILIENCE_FAILURE", "integrity": {"after": "PASS"}},
    )
    state.write(path / "metadata.json", {"scenario": "008-postgres-outage"})
    assert api.get("/api/runs").json()["items"][0]["result"] == "RESILIENCE_FAILURE"
    assert api.get("/api/runs/" + identifier).json()["summary"]["integrity"]["after"] == "PASS"
    assert api.get("/api/runs/" + identifier + "/artifacts/.env").status_code == 404
    (path / "integrity-before.json").symlink_to(path / "summary.json")
    assert (
        api.get("/api/runs/" + identifier + "/artifacts/integrity-before.json").status_code == 404
    )


def test_busy_job_rejects_second_start_but_abort_remains_available(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    service = api.app.state.jobs
    service.current = {
        "job_id": "job-active",
        "status": "RUNNING",
        "operation": "run",
        "started_at": time.time(),
    }
    token = headers(api)
    response = api.post(
        "/api/actions/preflight", json={"scenario": "002-worker-pause"}, headers=token
    )
    assert response.status_code == 409
    calls = []
    monkeypatch.setattr(service, "execute", lambda record: calls.append(record["operation"]))
    assert api.post("/api/actions/abort", json={}, headers=token).status_code == 202
    assert service.current["job_id"] == "job-active"
    # A read of a missing job is explicit rather than manufactured success.
    assert api.get("/api/jobs/job-missing").status_code == 404


def test_body_limits_and_database_opt_in(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    token = headers(api)
    assert (
        api.post("/api/actions/run", json={"scenario": "x" * 5000}, headers=token).status_code
        == 413
    )
    monkeypatch.setenv("ALLOW_DATABASE_CHAOS", "false")
    body = {"scenario": "008-postgres-outage", "confirm": "008-postgres-outage"}
    assert api.post("/api/actions/run", json=body, headers=token).status_code == 409


def test_subprocess_output_is_bounded():
    import io
    from chaos.workbench import capture_tail

    output = []
    capture_tail(io.BytesIO(b"x" * 1000000 + b"final"), output)
    assert len(output[0]) == 128 * 1024
    assert output[0].endswith(b"final")


def test_abort_cancels_run_before_native_lease_is_published(tmp_path, monkeypatch):
    import threading

    api = client(tmp_path, monkeypatch)
    service = api.app.state.jobs
    entered, unblock, finished = threading.Event(), threading.Event(), threading.Event()
    continued = []

    def pending(record):
        if record["operation"] == "run":
            entered.set()
            unblock.wait(2)
            if not record.get("cancel_requested"):
                continued.append("injection")
            finished.set()

    monkeypatch.setattr(service, "execute", pending)
    record = service.start("run", "002-worker-pause")
    assert entered.wait(1)
    assert state.active() is None
    service.start("abort", None)
    unblock.set()
    assert finished.wait(1)
    assert record.get("cancel_requested") is True
    assert continued == []


def test_abort_delegates_native_restore_to_finalize_interrupted_lease(tmp_path, monkeypatch):
    import io
    from chaos import workbench

    api = client(tmp_path, monkeypatch)
    commands = []

    class Child:
        returncode = 0
        pid = 999999

        def __init__(self, command, **kwargs):
            commands.append(command)
            self.stdout = io.BytesIO(b'{"status":"RESTORED"}\n')

        def wait(self, timeout):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(workbench.subprocess, "Popen", Child)
    record = {"job_id": "job-test", "operation": "abort", "scenario": None, "status": "RUNNING"}
    api.app.state.jobs.execute(record)
    assert [command[3] for command in commands] == ["abort", "restore"]
    assert record["status"] == "COMPLETED"


def test_run_cannot_overlap_abort_finalization(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    service = api.app.state.jobs
    service.current = {"status": "CANCELLED"}
    service.pending = {"job-abort": "abort"}
    monkeypatch.setattr(service, "execute", lambda record: None)
    token = headers(api)
    response = api.post(
        "/api/actions/run",
        json={"scenario": "002-worker-pause", "confirm": "002-worker-pause"},
        headers=token,
    )
    assert response.status_code == 409
