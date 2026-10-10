import time
import subprocess
import sys

from chaos import state, watchdog, restoration
from chaos.tests.test_gateway_authority import lease


def test_watchdog_restores_even_when_evidence_files_cannot_be_written(monkeypatch, tmp_path):
    value = lease()
    value["injection_started"] = True
    value.update(expires_epoch=time.time() - 1, revoked=False)
    monkeypatch.setattr(state, "CONTROL", tmp_path)

    def broken(*args, **kwargs):
        raise OSError("full evidence disk")

    monkeypatch.setattr(state, "event", broken)
    monkeypatch.setattr(state, "write", broken)
    calls = []

    class Docker:
        def lease(self):
            return value

        def revoke(self):
            calls.append("revoke")

        def call(self, *args, **kwargs):
            calls.append("confirmed")

    monkeypatch.setattr(watchdog, "Docker", Docker)
    monkeypatch.setattr(
        watchdog, "restore", lambda _: calls.append("restore") or {"status": "RESTORED"}
    )
    watchdog.tick()
    assert calls == ["revoke", "restore", "confirmed"]


def test_restore_is_idempotent_and_does_not_depend_on_evidence_writes(monkeypatch, tmp_path):
    value = lease()
    value["injection_started"] = True
    value["scenario"] = "001-api-pause"
    value["configuration"]["interface"] = "eth0"
    value["target"]["State"]["Paused"] = True
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    operations = []

    class Docker:
        def lease(self):
            return value

        def revoke(self):
            operations.append("revoke")

        def inspect(self, identifier):
            return value["target"]

        def call(self, method, path, **kwargs):
            if method == "GET":
                return []
            operations.append(path.rsplit("/", 1)[-1])
            if path.endswith("unpause"):
                value["target"]["State"]["Paused"] = False

    def broken(*args, **kwargs):
        raise OSError("full evidence disk")

    monkeypatch.setattr(state, "event", broken)
    monkeypatch.setattr(state, "write", broken)
    monkeypatch.setattr(restoration, "Docker", Docker)
    assert restoration.restore(value)["status"] == "RESTORED"
    assert restoration.restore(value)["status"] == "RESTORED"
    assert operations.count("unpause") == 1


def test_parallel_restoration_accepts_helper_already_removed(monkeypatch, tmp_path):
    value = lease()
    value["injection_started"] = True
    value["scenario"] = "001-api-pause"
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    calls = []
    helper = {
        "Id": "b" * 64,
        "State": "running",
        "Labels": {
            "io.pulsepay.chaos.run": value["run_id"],
            "io.pulsepay.chaos.helper": "true",
        },
    }

    class Docker:
        def lease(self):
            return value

        def revoke(self):
            pass

        def inspect(self, identifier):
            return value["target"]

        def call(self, method, path, **kwargs):
            if method == "GET":
                calls.append("list")
                return [helper] if len(calls) == 1 else []
            if path.endswith("stop?t=2"):
                raise RuntimeError("Other restorer already removed the owned helper")

    monkeypatch.setattr(restoration, "Docker", Docker)
    assert restoration.restore(value)["status"] == "RESTORED"
    assert len(calls) == 2


def test_expired_watchdog_restores_without_reading_runner_heartbeat(monkeypatch, tmp_path):
    value = lease()
    value.update(expires_epoch=time.time() - 1, revoked=False)
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    calls = []

    class Docker:
        def lease(self):
            return value

        def revoke(self):
            calls.append("revoke")

        def call(self, *args, **kwargs):
            calls.append("confirmed")

    def unsafe_read(*args, **kwargs):
        raise AssertionError("TTL restoration cannot depend on runner mailbox reads")

    monkeypatch.setattr(state, "read", unsafe_read)
    monkeypatch.setattr(state, "safe_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(state, "safe_write", lambda *args, **kwargs: None)
    monkeypatch.setattr(watchdog, "Docker", Docker)
    monkeypatch.setattr(
        watchdog, "restore", lambda _: calls.append("restore") or {"status": "RESTORED"}
    )
    watchdog.tick()
    assert calls == ["revoke", "restore", "confirmed"]


def test_restore_lock_fifo_does_not_block_cleanup(tmp_path):
    program = """
import os
from pathlib import Path
from chaos import state, restoration
from chaos.tests.test_gateway_authority import lease
value=lease(); root=Path(__import__('sys').argv[1]); state.CONTROL=root
directory=root/value['run_id']; directory.mkdir()
os.mkfifo(directory/'restore.lock')
class Docker:
    def lease(self): return value
    def revoke(self): pass
restoration.Docker=Docker
restoration.restore_locked=lambda *args: {'status':'RESTORED'}
assert restoration.restore(value)['status']=='RESTORED'
"""
    subprocess.run([sys.executable, "-c", program, str(tmp_path)], check=True, timeout=2)
