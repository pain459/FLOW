import importlib.util

import pytest


def module():
    assert importlib.util.find_spec("decision_engine.controller.sessions"), (
        "session controller missing"
    )
    from decision_engine.controller import sessions

    return sessions


def test_run_sequence_rejects_future_and_duplicate_order():
    m = module()
    with pytest.raises(ValueError):
        m.validate_sequence(
            [{"observed_at": "2026-10-11T01:00:01Z"}, {"observed_at": "2026-10-11T01:00:00Z"}]
        )
    with pytest.raises(ValueError):
        m.validate_sequence([{"observed_at": "2026-10-11T01:00:01Z"}] * 2)


def test_session_content_hash_is_canonical_and_bounded():
    m = module()
    assert m.hash_payload({"b": 2, "a": 1}) == m.hash_payload({"a": 1, "b": 2})
    with pytest.raises(ValueError):
        m.hash_payload({"bad": float("inf")})


def test_decision_budget_begins_at_causally_confirmed_incident_not_file_prefix():
    healthy = {
        "database": {"reachable": True},
        "redis": {"reachable": True},
        "api": {"error_rate_pct": 0},
        "worker": {"outbox_oldest_seconds": 0},
    }
    impaired = {**healthy, "database": {"reachable": False}}
    history = [healthy] * 12 + [impaired, impaired, healthy]
    assert module().replay_start(history) == {
        "start_index": 13,
        "triggered": True,
        "version": "sustained-observation-v1",
    }
    assert module().replay_start([healthy, impaired, healthy])["triggered"] is False
