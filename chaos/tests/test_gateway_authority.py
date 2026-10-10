import copy
import io
import time
import subprocess
import sys

import pytest

from chaos import gateway, state
from chaos.policy import NETTOOLS_IMAGE, bound_configuration, validate_helper
from chaos.tests.test_safety_guards import target
from chaos.adapters import toxiproxy


def lease():
    value = target()
    value["HostConfig"] = {"RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0}}
    return {
        "run_id": "chaos-test",
        "scenario": "004-api-network-delay",
        "target": value,
        "configuration": bound_configuration("004-api-network-delay", {}),
        "armed": True,
        "expires_epoch": time.time() + 60,
    }


@pytest.mark.parametrize(
    "armed,fresh,aborted",
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_injecting_helper_cannot_start_without_independent_guard(
    monkeypatch, tmp_path, armed, fresh, aborted
):
    frozen = lease()
    frozen["armed"] = armed
    if not fresh:
        frozen["expires_epoch"] = time.time() - 1
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    root = tmp_path / frozen["run_id"]
    state.write(root / "heartbeat.json", {"epoch": time.time()})
    state.write(root / "watchdog-armed.json", {"epoch": time.time()})
    if aborted:
        (root / "abort").touch()
    helper = {
        "Id": "b" * 64,
        "Config": {
            "Image": NETTOOLS_IMAGE,
            "Labels": {
                "io.pulsepay.chaos.run": frozen["run_id"],
                "io.pulsepay.chaos.helper": "true",
                "io.pulsepay.chaos.project": "chaosloop",
                "io.pulsepay.chaos.purpose": "network_inject",
            },
        },
    }
    monkeypatch.setattr(gateway, "inspect", lambda _: (helper, True))
    monkeypatch.setattr(gateway, "current_lease", lambda: frozen, raising=False)
    monkeypatch.setattr(state, "active", lambda: frozen)
    monkeypatch.setattr(gateway, "watchdog_fresh", lambda _: True, raising=False)
    with pytest.raises(ValueError):
        gateway.authorization(helper["Id"], "start")


def test_gateway_revalidates_duration_and_target_role():
    frozen = lease()
    frozen["configuration"]["duration_seconds"] = 86400
    body = {
        "Image": NETTOOLS_IMAGE,
        "Entrypoint": ["tail"],
        "Cmd": ["-f", "/dev/null"],
        "HostConfig": {"NetworkMode": "container:" + frozen["target"]["Id"]},
    }
    with pytest.raises(ValueError):
        validate_helper(body, frozen, "chaosloop")
    frozen = lease()
    frozen["target"] = target("postgres")
    with pytest.raises(ValueError):
        validate_helper(body, frozen, "chaosloop")


def test_negative_content_length_is_rejected_without_read(monkeypatch):
    handler = object.__new__(gateway.Handler)
    handler.path, handler.command = "/health", "GET"
    handler.headers = {"Content-Length": "-1"}
    handler.rfile = io.BytesIO(b"x" * 65538)
    replies = []
    handler.reply = lambda *args: replies.append(args)
    monkeypatch.setattr(state, "event", lambda *args, **kwargs: None)
    handler.handle_api()
    assert replies[0][0] == 403
    assert handler.rfile.tell() == 0


def test_runner_writable_lease_cannot_replace_gateway_authority(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "CONTROL", tmp_path / "runner")
    monkeypatch.setattr(gateway, "AUTHORITY", tmp_path / "gate", raising=False)
    root = gateway.AUTHORITY / "chaos-test"
    state.write(gateway.AUTHORITY / "active.json", {"run_id": "chaos-test"})
    original = lease()
    state.write(root / "lease.json", original)
    forged = copy.deepcopy(original)
    forged["expires_epoch"] = time.time() + 86400
    state.write(state.CONTROL / "active.json", {"run_id": "chaos-test"})
    state.write(state.CONTROL / "chaos-test" / "lease.json", forged)
    assert gateway.current_lease()["expires_epoch"] == original["expires_epoch"]


@pytest.mark.parametrize("purpose", ["network_read", "network_restore", "capability"])
def test_read_helpers_cannot_execute_netem_start(monkeypatch, purpose):
    frozen = lease()
    helper = {
        "Id": "b" * 64,
        "Config": {
            "Labels": {
                "io.pulsepay.chaos.run": frozen["run_id"],
                "io.pulsepay.chaos.purpose": purpose,
            }
        },
    }
    monkeypatch.setattr(gateway, "current_lease", lambda: frozen)
    monkeypatch.setattr(gateway, "inspect", lambda _: (helper, True))
    with pytest.raises(ValueError):
        gateway.authorization(helper["Id"], "inject_exec")


def test_gateway_never_writes_runner_owned_symlink_paths(monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.write_text("unchanged watchdog token")
    control = tmp_path / "runner"
    root = control / "chaos-test"
    root.mkdir(parents=True)
    (root / "lease.json").symlink_to(private)
    monkeypatch.setattr(state, "CONTROL", control)
    gateway.mirror_lease(lease())
    assert private.read_text() == "unchanged watchdog token"


@pytest.mark.parametrize("scenario", ["005-db-network-delay", "007-redis-network-partition"])
def test_proxy_gate_never_writes_runner_owned_evidence(monkeypatch, scenario):
    frozen = lease()
    frozen.update(scenario=scenario, proxy_before={"enabled": True})
    frozen["configuration"]["delay_ms"] = 150
    monkeypatch.setattr(toxiproxy, "runtime_call", lambda *args: {})

    def unsafe_write(*args, **kwargs):
        raise AssertionError("Root gateway must not write runner-owned evidence")

    monkeypatch.setattr(state, "safe_event", unsafe_write)
    assert toxiproxy.runtime_inject(frozen)["confirmed"]


def test_expired_gate_lease_denied_before_reading_runner_mailbox(monkeypatch):
    frozen = lease()
    frozen["expires_epoch"] = time.time() - 1

    def unsafe_read(*args, **kwargs):
        raise AssertionError("Expired authority must be evaluated before mailbox reads")

    monkeypatch.setattr(state, "read", unsafe_read)
    with pytest.raises(ValueError):
        gateway.injection_guard(frozen)


def test_shared_json_reads_reject_symlinks_and_oversized_files(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text('{"epoch": 123}')
    mailbox = tmp_path / "heartbeat.json"
    mailbox.symlink_to(secret)
    assert state.read(mailbox, {}) == {}
    mailbox.unlink()
    mailbox.write_text('{"epoch": 123}' + " " * 4096)
    assert state.read(mailbox, {}, max_bytes=4096) == {}


def test_qdisc_probe_cannot_overwrite_concurrent_revocation(monkeypatch):
    frozen = lease()
    frozen.update(armed=False, revoked=True)
    monkeypatch.setattr(gateway, "current_lease", lambda: frozen)
    saves = []
    monkeypatch.setattr(gateway.authority, "save", lambda *args: saves.append(args))
    with pytest.raises(ValueError):
        gateway.record_clean_qdisc(frozen["run_id"], "qdisc noqueue 0: root")
    assert not saves


def test_evidence_fifo_cannot_block_restoration(tmp_path):
    program = """
import os
from pathlib import Path
from chaos import state
root=Path(__import__('sys').argv[1])
state.CONTROL=root/'control'; state.EVIDENCE=root/'evidence'
state.write(state.CONTROL/'active.json', {'run_id':'chaos-test'})
state.write(state.CONTROL/'chaos-test'/'lease.json', {'run_id':'chaos-test'})
timeline=state.EVIDENCE/'chaos-test'/'timeline.jsonl'
timeline.parent.mkdir(parents=True)
os.mkfifo(timeline)
state.safe_event('RESTORING')
target=root/'report.json'
os.mkfifo(target.with_suffix('.json.'+str(os.getpid())+'.tmp'))
state.write(target, {'restored':True})
assert state.read(target)['restored']
"""
    subprocess.run([sys.executable, "-c", program, str(tmp_path)], check=True, timeout=2)


def test_gate_restart_revokes_persisted_lease_even_with_full_authority_disk(monkeypatch):
    frozen = lease()
    monkeypatch.setattr(gateway, "REVOKED", set())
    monkeypatch.setattr(gateway.authority, "active", lambda _: copy.deepcopy(frozen))

    def full_disk(*args):
        raise OSError("full authority disk")

    monkeypatch.setattr(gateway.authority, "save", full_disk)
    gateway.recover_authority()
    assert gateway.current_lease()["revoked"]
    with pytest.raises(ValueError):
        gateway.injection_guard(gateway.current_lease())


def test_toxiproxy_normalized_wildcard_listener_keeps_exact_route(monkeypatch):
    current = {"listen": "[::]:15432", "upstream": "postgres:5432", "enabled": True}
    monkeypatch.setattr(toxiproxy, "runtime_call", lambda *args: current)
    assert toxiproxy.runtime_snapshot("api_postgres") == current
    current["upstream"] = "unrelated:5432"
    with pytest.raises(ValueError):
        toxiproxy.runtime_snapshot("api_postgres")


@pytest.mark.parametrize("pointer", [1, [1], {"run_id": 1}, {"run_id": "../../private"}])
def test_malformed_logging_mailbox_cannot_interrupt_cleanup(monkeypatch, tmp_path, pointer):
    monkeypatch.setattr(state, "CONTROL", tmp_path)
    state.write(tmp_path / "active.json", pointer)
    assert state.active() is None
    state.safe_event("RESTORING")


def test_repeated_injection_cannot_extend_private_fault_deadline(monkeypatch):
    frozen = lease()
    frozen.update(armed=True, revoked=False)
    monkeypatch.setattr(gateway, "current_lease", lambda: frozen)
    monkeypatch.setattr(gateway, "injection_guard", lambda _: None)
    monkeypatch.setattr(gateway.authority, "save", lambda *args: None)
    gateway.mark_injection()
    deadline = frozen["fault_deadline_epoch"]
    gateway.mark_injection()
    assert frozen["fault_deadline_epoch"] == deadline
    assert deadline <= time.time() + frozen["configuration"]["duration_seconds"] + 15


def test_old_watchdog_ack_cannot_arm_reused_authority_id(monkeypatch, tmp_path):
    from chaos import authority

    frozen = lease()
    frozen["created_epoch"] = time.time()
    state.write(
        tmp_path / frozen["run_id"] / "watchdog-armed.json", {"epoch": frozen["created_epoch"] - 1}
    )
    assert not authority.watchdog_fresh(frozen, tmp_path)
    monkeypatch.setattr(authority, "AUTHORITY", tmp_path)
    with pytest.raises(ValueError):
        authority.freeze(
            {
                "run_id": frozen["run_id"],
                "scenario": frozen["scenario"],
                "configuration": {},
                "target_id": frozen["target"]["Id"],
            },
            "chaosloop",
            frozen["target"],
        )
