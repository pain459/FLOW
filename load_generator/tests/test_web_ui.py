from flask import Flask
from types import SimpleNamespace
from load_generator.controller.schemas import Profile
from load_generator.tests.test_contracts import profile_values


def test_finishing_manual_session_stops_runner_and_web_server():
    from load_generator.workloads.web_ui import quit_ui

    calls = []
    environment = SimpleNamespace(
        runner=SimpleNamespace(quit=lambda: calls.append("runner")),
        web_ui=SimpleNamespace(stop=lambda: calls.append("web")),
    )
    quit_ui(environment)
    assert calls == ["runner", "web"]


def test_finishing_stack_session_stops_traffic_and_keeps_web_server(monkeypatch):
    from load_generator.workloads.web_ui import quit_ui

    monkeypatch.setenv("LOAD_STACK_UI", "true")
    calls = []
    environment = SimpleNamespace(
        runner=SimpleNamespace(stop=lambda: calls.append("traffic")),
        web_ui=SimpleNamespace(stop=lambda: calls.append("web")),
    )
    quit_ui(environment)
    assert calls == ["traffic"]


def test_ui_supervisor_failure_stops_traffic(monkeypatch):
    from load_generator.workloads.web_ui import supervise_safely

    monkeypatch.setenv("LOAD_STACK_UI", "true")
    calls = []
    environment = SimpleNamespace(
        runner=SimpleNamespace(stop=lambda: calls.append("stopped"))
    )

    def disk_failure():
        raise OSError("disk full")

    supervise_safely(environment, disk_failure)
    assert calls == ["stopped"]


def test_manual_ui_rejects_external_targets_and_excessive_users_before_swarm():
    from load_generator.workloads.web_ui import install_guard

    app = Flask(__name__)
    profile = Profile.model_validate(profile_values())
    environment = SimpleNamespace(web_ui=SimpleNamespace(app=app))
    install_guard(environment, profile)

    @app.post("/swarm")
    def swarm():
        return {"started": True}

    with app.test_client() as client:
        assert (
            client.post(
                "/swarm",
                data={
                    "user_count": "2",
                    "spawn_rate": "1",
                    "host": "https://example.com",
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/swarm",
                data={
                    "user_count": "151",
                    "spawn_rate": "1",
                    "host": "http://api:8080",
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/swarm",
                data={
                    "user_count": "2",
                    "spawn_rate": "nan",
                    "host": "http://api:8080",
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/swarm",
                data={"user_count": "2", "spawn_rate": "1", "host": "http://api:8080"},
            ).status_code
            == 200
        )


def test_manual_ui_rejects_scheduling_restart_and_unknown_user_classes():
    from load_generator.workloads.web_ui import install_guard

    app = Flask(__name__)
    environment = SimpleNamespace(web_ui=SimpleNamespace(app=app))
    install_guard(environment, Profile.model_validate(profile_values()))

    @app.post("/swarm")
    def swarm():
        return {"started": True}

    with app.test_client() as client:
        values = {"user_count": "2", "spawn_rate": "1", "host": "http://api:8080"}
        assert (
            client.post("/user", json={"host": "https://example.com"}).status_code
            == 403
        )
        assert (
            client.post("/swarm", data={**values, "run_time": "100h"}).status_code
            == 400
        )
        assert (
            client.post(
                "/swarm", data={**values, "user_classes": "OtherUser"}
            ).status_code
            == 400
        )
        assert (
            client.post("/swarm", data={**values, "stop_timeout": "bad"}).status_code
            == 400
        )
