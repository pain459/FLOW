import hashlib
import importlib
import importlib.util
import json

import pytest


def test_sealed_evidence_can_produce_a_separate_provenance_linked_evaluator_label():
    assert importlib.util.find_spec("chaos.evaluator") is not None


def files():
    values = {
        "metadata.json": {
            "run_id": "chaos-fixture",
            "scenario": "002-worker-pause",
            "configuration": {"duration_seconds": 20},
            "git_sha": "a" * 40,
        },
        "summary.json": {"run_id": "chaos-fixture", "result": "PASS"},
        "injector-result.json": {"exit_code": 0},
        "impact.json": {"observed": True, "first_observed_at": "2026-10-10T00:00:05Z"},
        "chaostoolkit-journal.json": {
            "run": [
                {
                    "activity": {"name": "apply-bounded-framework-fault"},
                    "status": "succeeded",
                    "start": "2026-10-10T00:00:01Z",
                    "end": "2026-10-10T00:00:02Z",
                }
            ]
        },
        "restoration.json": {"status": "RESTORED", "finished_at": "2026-10-10T00:00:24Z"},
    }
    result = {name: json.dumps(value).encode() for name, value in values.items()}
    result["checksums.json"] = json.dumps(
        {name: hashlib.sha256(data).hexdigest() for name, data in result.items()}
    ).encode()
    return result


def evaluator():
    return importlib.import_module("chaos.evaluator")


def test_derived_label_uses_injector_and_effect_evidence_without_relabelling_source():
    original = files()
    before = dict(original)
    label = evaluator().derive_ground_truth(original)
    assert label["injection_confirmed"] is True
    assert label["effect_confirmed"] is True
    assert label["source_result"] == "PASS"
    assert label["provenance"]["injection_confirmed"] == [
        "injector-result.json",
        "chaostoolkit-journal.json",
    ]
    assert label["actual_fault_end"] is None
    assert label["restoration_verified_at"] == "2026-10-10T00:00:24Z"
    assert original == before


def test_pass_summary_without_injector_evidence_cannot_invent_confirmation():
    original = files()
    original.pop("injector-result.json")
    original.pop("checksums.json")
    original["checksums.json"] = json.dumps(
        {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
    ).encode()
    label = evaluator().derive_ground_truth(original)
    assert label["injection_confirmed"] is None
    assert "injection_confirmed" in label["missing_evidence"]
    assert label["source_result"] == "PASS"


def test_tampered_source_is_refused_without_derivation():
    original = files()
    original["impact.json"] = b'{"observed": false}'
    with pytest.raises(ValueError, match="hash"):
        evaluator().derive_ground_truth(original)


def test_original_preflight_target_is_retained_with_exact_id_provenance():
    original = files()
    original.pop("checksums.json")
    original["preflight.json"] = json.dumps(
        {"target": {"Id": "b" * 64, "Name": "/lab-worker"}}
    ).encode()
    original["checksums.json"] = json.dumps(
        {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}
    ).encode()
    label = evaluator().derive_ground_truth(original)
    assert label["target"]["Id"] == "b" * 64
    assert "target" not in label["missing_evidence"]
