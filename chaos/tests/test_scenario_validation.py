import pytest

from chaos import state
from chaos.preflight import validate
from chaos.policy import SCENARIOS
from chaos.authority import freeze
from chaos.tests.test_gateway_authority import lease


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_native_toolkit_accepts_every_committed_experiment(scenario):
    _, experiment, config = validate(scenario)
    assert experiment["rollbacks"]
    assert 3 <= config["duration_seconds"] <= 40


def test_invalid_named_scenario_never_reaches_toolkit():
    with pytest.raises(ValueError):
        validate("re2:.*")


def test_exclusive_lease_and_lingering_restore_cannot_overlap(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    with state.ExperimentLock():
        with pytest.raises(RuntimeError):
            with state.ExperimentLock():
                pytest.fail("overlapping lock accepted")
    state.write(tmp_path / "active.json", {"run_id": "chaos-stale"})
    state.write(tmp_path / "chaos-stale" / "lease.json", {"run_id": "chaos-stale"})
    with pytest.raises(RuntimeError):
        with state.ExperimentLock():
            pytest.fail("unverified stale lease ignored")


def test_database_opt_in_is_enforced_at_gateway_not_only_cli(monkeypatch):
    value = lease()
    request = {
        "run_id": value["run_id"],
        "scenario": "008-postgres-outage",
        "configuration": value["configuration"],
        "target_id": value["target"]["Id"],
    }
    monkeypatch.delenv("ALLOW_DATABASE_CHAOS", raising=False)
    with pytest.raises(ValueError, match="ALLOW_DATABASE_CHAOS"):
        freeze(request, "chaosloop", value["target"])
