import hashlib
import json
from uuid import uuid4

import pytest

from decision_engine.export_bundles import export


def test_export_is_sealed_idempotent_and_refuses_changed_existing_evidence(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    folder = source / str(uuid4())
    folder.mkdir()
    report = folder / "summary.json"
    report.write_text('{"state":"INCONCLUSIVE"}')
    (folder / "checksums.json").write_text(
        json.dumps({"files": {"summary.json": hashlib.sha256(report.read_bytes()).hexdigest()}})
    )
    assert export(source, target)["copied"] == 1
    assert export(source, target)["unchanged"] == 1
    (target / folder.name / "summary.json").write_text("changed")
    with pytest.raises(ValueError, match="differs"):
        export(source, target)


def test_export_rejects_unsealed_tampering_without_silently_changing_source(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    folder = source / str(uuid4())
    folder.mkdir()
    assert export(source, target)["partial_retained_on_volume"] == 1
    (folder / "checksums.json").write_text(json.dumps({"files": {"../secret": "a" * 64}}))
    with pytest.raises(ValueError, match="seal mismatch"):
        export(source, target)
