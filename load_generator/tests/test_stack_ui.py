from types import SimpleNamespace

import pytest


def test_report_write_failure_releases_lock_and_retains_recovery_pointer(tmp_path, monkeypatch):
    from load_generator import stack_ui
    from load_generator.controller.lifecycle import RunLock

    monkeypatch.setenv("LOAD_REPORTS", str(tmp_path))
    active = tmp_path / "active.json"
    active.write_text('{"run_id":"load-ui-example"}')
    path = tmp_path / "load-ui-example"
    path.mkdir()
    lock = RunLock(tmp_path).__enter__()
    monkeypatch.setattr(stack_ui, "LOCK", lock)
    monkeypatch.setenv("LOAD_TARGET", "http://api:8080")
    monkeypatch.setattr(
        stack_ui,
        "Observer",
        lambda target: SimpleNamespace(cooldown=lambda seconds: None, close=lambda: None),
    )
    monkeypatch.setattr(stack_ui, "independent_verification", lambda: {"status": "PASS"})

    def full_disk(*args):
        raise OSError("disk full")

    monkeypatch.setattr(stack_ui, "atomic_json", full_disk)
    with pytest.raises(OSError):
        stack_ui.finish(path, SimpleNamespace(phases={}), SimpleNamespace(cooldown_seconds=1))
    assert stack_ui.LOCK is None
    assert active.exists()
    with RunLock(tmp_path):
        pass
