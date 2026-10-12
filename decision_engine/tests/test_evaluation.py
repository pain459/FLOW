import importlib.util
import hashlib
import json

import pytest


def scorer():
    assert importlib.util.find_spec("decision_engine.evaluation.scorer"), (
        "independent evaluator missing"
    )
    from decision_engine.evaluation import scorer

    return scorer


def test_ineffective_fault_not_accepted_positive():
    assert (
        scorer().eligible({"result": "PASS", "injection_confirmed": True, "impact_observed": False})
        is False
    )


def test_effective_fault_accepted_only_with_verified_native_result():
    assert (
        scorer().eligible({"result": "PASS", "injection_confirmed": True, "impact_observed": True})
        is True
    )


def test_intervals_reflect_small_sample_uncertainty():
    low, high = scorer().wilson(1, 2)
    assert low < 0.2 and high > 0.8
    assert scorer().wilson(0, 0) == [None, None]


def test_ranking_reports_observed_label_mass_not_recovery_probability():
    r = scorer().score_distribution(
        {"redis": 0.6, "network": 0.3, "api": 0.1}, {"redis", "network"}
    )
    assert r["top1_correct"] and r["supported_label_mass"] == pytest.approx(0.9)
    assert "probability_of_recovery" not in r


def test_evaluator_rejects_changed_evidence_and_path_traversal(tmp_path):
    p = tmp_path / "summary.json"
    p.write_text("{}")
    (tmp_path / "checksums.json").write_text(
        json.dumps({"summary.json": hashlib.sha256(p.read_bytes()).hexdigest()})
    )
    assert scorer().verify_seal(tmp_path)
    p.write_text('{"tampered":true}')
    assert not scorer().verify_seal(tmp_path)
    (tmp_path / "checksums.json").write_text(json.dumps({"../secret": "f" * 64}))
    assert not scorer().verify_seal(tmp_path)


def test_prefault_controls_use_full_causal_source_not_exported_incident_slice():
    healthy = {
        "observed_at": "2026-10-11T01:00:00+00:00",
        "database": {"reachable": True},
        "redis": {"reachable": True},
        "api": {"error_rate_pct": 0},
        "worker": {"outbox_oldest_seconds": 0},
    }
    states = [healthy, {**healthy, "observed_at": "2026-10-11T01:00:10+00:00"}]
    result = scorer().prefault_controls(states, "2026-10-11T01:00:15+00:00")
    assert result == {"samples": 2, "false_alarms": 0, "status": "OBSERVED"}
    assert scorer().prefault_controls(states, None)["samples"] is None


def test_evaluator_rejects_source_hash_or_causal_slice_mismatch():
    healthy = {
        "database": {"reachable": True},
        "redis": {"reachable": True},
        "api": {"error_rate_pct": 0},
        "worker": {"outbox_oldest_seconds": 0},
    }
    impaired = {**healthy, "redis": {"reachable": False}}
    states = [healthy, impaired, impaired]
    plan = {"start_index": 2, "triggered": True, "version": "sustained-observation-v1"}
    assert scorer().valid_causal_replay(states, [impaired], plan, "a" * 64, "a" * 64)
    assert not scorer().valid_causal_replay(states, [healthy], plan, "a" * 64, "a" * 64)
    assert not scorer().valid_causal_replay(states, [impaired], plan, "a" * 64, "b" * 64)
