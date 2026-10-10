import pytest

from load_generator.controller.storage import check_report_budget


def test_report_budget_refuses_new_traffic_without_removing_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LOAD_REPORT_BUDGET_MIB", "1")
    evidence = tmp_path / "historical.json"
    evidence.write_bytes(b"x" * (1024**2))
    with pytest.raises(ValueError, match="REPORT_STORAGE_BUDGET_EXCEEDED"):
        check_report_budget(tmp_path, reserve_bytes=1)
    assert evidence.stat().st_size == 1024**2


def test_report_budget_rejects_unbounded_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LOAD_REPORT_BUDGET_MIB", "0")
    with pytest.raises(ValueError):
        check_report_budget(tmp_path)
