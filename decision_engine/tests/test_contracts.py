import copy
import importlib.util
import math

import pytest


def contract_module():
    assert importlib.util.find_spec("decision_engine.models.contracts"), (
        "typed provider contract missing"
    )
    from decision_engine.models import contracts

    return contracts


def answer():
    return {
        "answers": {
            "subsystem": {
                "type": "choice",
                "choice": "api",
                "probabilities": {"api": 0.7, "unknown": 0.3},
                "confidence": 0.4,
                "answer_confidence": 0.7,
                "action": {"act_probability": 1.0},
            },
            "severity": {
                "type": "score",
                "score": 0.3,
                "legend": {"0": "minor", "1": "major"},
                "probabilities": {"0": 0.7, "1": 0.3},
                "confidence": 0.4,
                "answer_confidence": 0.7,
                "action": {"act_probability": 1.0},
            },
            "more": {
                "type": "noul",
                "noul": 0.8,
                "confidence": 0.8,
                "answer_confidence": 0.8,
                "action": {"act_probability": 1.0},
            },
        }
    }


Q = {
    "subsystem": {"type": "choice", "criteria": {"api": "requests", "unknown": "missing"}},
    "severity": {"type": "score", "criteria": ["minor", "major"]},
    "more": {"type": "noul"},
}


def test_types_preserve_expected_ordinal_and_probability():
    c = contract_module()
    result = c.normalize_answers(answer(), Q)
    assert result["severity"]["score"] == 0.3
    assert result["severity"]["most_likely_level"] == "minor"
    assert result["more"]["noul"] == 0.8
    assert not isinstance(result["more"]["noul"], bool)


@pytest.mark.parametrize(
    "change",
    ["unknown_choice", "nan", "boolean", "bad_sum", "missing", "wrong_mean", "unrequested"],
)
def test_invalid_provider_answer_rejected(change):
    c = contract_module()
    raw = copy.deepcopy(answer())
    if change == "unknown_choice":
        raw["answers"]["subsystem"]["choice"] = "restart_database"
    if change == "nan":
        raw["answers"]["more"]["noul"] = math.nan
    if change == "boolean":
        raw["answers"]["more"]["noul"] = True
    if change == "bad_sum":
        raw["answers"]["severity"]["probabilities"]["0"] = 0.5
    if change == "missing":
        del raw["answers"]["more"]
    if change == "wrong_mean":
        raw["answers"]["severity"]["score"] = 0.9
    if change == "unrequested":
        raw["answers"]["write"] = raw["answers"]["more"]
    with pytest.raises(ValueError):
        c.normalize_answers(raw, Q)


@pytest.mark.parametrize("field,value", [("choice", "FAULT_TRUTH_CANARY"), ("noul", 0.5)])
def test_score_rejects_other_answer_heads(field, value):
    raw = answer()
    raw["answers"]["severity"][field] = value
    with pytest.raises(ValueError):
        contract_module().normalize_answers(raw, Q)


def test_optional_confidence_head_cannot_carry_ground_truth():
    raw = answer()
    raw["answers"]["subsystem"]["x_jev_confidence"] = "FAULT_TRUTH_CANARY"
    with pytest.raises(ValueError):
        contract_module().normalize_answers(raw, Q)
