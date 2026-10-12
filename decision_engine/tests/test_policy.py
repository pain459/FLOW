import importlib.util

import pytest


def modules():
    assert importlib.util.find_spec("decision_engine.controller.policy"), "bounded policy missing"
    from decision_engine.controller.policy import authorize, detected, baseline

    return authorize, detected, baseline


def state():
    return {
        "api": {"error_rate_pct": 0},
        "database": {"reachable": True, "connection_usage_pct": 10},
        "redis": {"reachable": True},
        "worker": {"outbox_pending": 0, "outbox_oldest_seconds": 0},
        "integrity": {"status": "PASS"},
        "source_quality": {"api": "FRESH", "dependencies": "FRESH", "integrity": "FRESH"},
    }


@pytest.mark.parametrize(
    "tool", ["restart_database", "docker", "http://evil", "inspect_database; DROP TABLE accounts"]
)
def test_unregistered_actions_rejected(tool):
    authorize, _, _ = modules()
    assert authorize(tool, state(), step=0, mode="shadow")["verdict"] == "REJECT"


def test_shadow_never_executes_and_readonly_gate_fails_closed():
    authorize, _, _ = modules()
    assert authorize("inspect_database", state(), step=0, mode="shadow")["execute"] is False
    assert authorize("inspect_database", state(), step=0, mode="readonly")["verdict"] == "REJECT"


def test_budget_and_integrity_override_model():
    authorize, _, _ = modules()
    assert authorize("inspect_api", state(), step=8, mode="shadow")["verdict"] == "ESCALATE"
    s = state()
    s["integrity"]["status"] = "FAIL"
    assert authorize("inspect_api", s, step=0, mode="shadow")["verdict"] == "ESCALATE"


def test_healthy_control_and_baseline_use_only_available_symptoms():
    _, detected, baseline = modules()
    s = state()
    assert not detected([s, s])
    s["redis"]["reachable"] = False
    assert detected([s, s])
    assert baseline(s)["subsystem"] == "redis"


def test_sustained_window_requires_two_distinct_observations():
    _, detected, _ = modules()
    s = state()
    s["api"]["error_rate_pct"] = 20
    assert not detected([s])
