import copy
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    assert importlib.util.find_spec("decision_engine.models.observation"), (
        "model observation projection missing"
    )
    from decision_engine.models import observation

    return observation


@pytest.fixture
def snapshot():
    p = next(Path("/public").glob("*/latest.json"))
    return json.loads(p.read_text())


def test_model_projection_has_no_run_or_path_identifiers(snapshot):
    state = module().from_snapshot(snapshot)
    raw = json.dumps(state.model_dump(mode="json"))
    assert snapshot["run_id"] not in raw
    assert "chaos-" not in raw
    assert state.worker.consumer_lag_seconds is None


@pytest.mark.parametrize("location", ["top", "api", "quality", "actions"])
def test_canary_contamination_never_reaches_model(snapshot, location):
    canary = "FAULT_TRUTH_CANARY_pause_postgres"
    s = copy.deepcopy(snapshot)
    if location == "top":
        s["scenario"] = canary
    if location == "api":
        s["api"]["message"] = canary
    if location == "quality":
        s["missing_observations"].append(canary)
    if location == "actions":
        s["available_investigations"].append(canary)
    with pytest.raises(ValueError):
        module().from_snapshot(s)


def test_stale_integrity_not_relabelled_healthy(snapshot):
    s = copy.deepcopy(snapshot)
    s["integrity"]["status"] = "UNKNOWN"
    s["freshness"]["sources"]["integrity"]["status"] = "STALE"
    s["freshness"]["sources"]["integrity"]["age_seconds"] = 120
    s["missing_observations"] = sorted(set(s["missing_observations"]) | {"integrity.status"})
    s["freshness"]["sources"]["integrity"]["observed_at"] = None
    with pytest.raises(ValueError):
        module().from_snapshot(s)
