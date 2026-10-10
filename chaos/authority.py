"""Gateway-owned authorization lease; no workload or experiment sequencing."""

import os
import re
import secrets
import time
from pathlib import Path

from chaos import state
from chaos.policy import SCENARIOS, allowed_target, bound_configuration

AUTHORITY = Path(os.getenv("CHAOS_AUTHORITY", "/authority"))


def private_write(path, value):
    state.write(path, value)
    path.chmod(0o640)
    if os.getuid() == 0:
        os.chown(path, 0, 1001)
        for directory in (path.parent, AUTHORITY):
            directory.chmod(0o750)
            os.chown(directory, 0, 1001)


def initialize():
    if os.getuid() == 0:
        for shared in (state.CONTROL, state.EVIDENCE):
            shared.mkdir(parents=True, exist_ok=True)
            os.chown(shared, 0, 1001)
            shared.chmod(0o770)
    AUTHORITY.mkdir(parents=True, exist_ok=True)
    token = AUTHORITY / "watchdog-token"
    if not token.exists():
        token.write_text(secrets.token_hex(32))
    token.chmod(0o640)
    if os.getuid() == 0:
        os.chown(token, 0, 1001)
        AUTHORITY.chmod(0o750)
        os.chown(AUTHORITY, 0, 1001)


def active(root=None):
    root = root or AUTHORITY
    pointer = state.read(root / "active.json", {})
    identifier = pointer.get("run_id", "")
    if not identifier:
        return None
    if not re.fullmatch(r"chaos-[a-zA-Z0-9_-]{1,80}", identifier):
        raise ValueError("Invalid authority pointer")
    return state.read(root / identifier / "lease.json")


def freeze(request, project, target):
    if set(request) != {"run_id", "scenario", "configuration", "target_id"}:
        raise ValueError("Unsupported authorization lease field")
    run_id = request["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"chaos-[a-zA-Z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid authorization lease ID")
    if (AUTHORITY / run_id).exists():
        raise ValueError("Authorization lease IDs cannot be reused")
    config = bound_configuration(
        request["scenario"],
        request["configuration"],
        os.getenv("ALLOW_DATABASE_CHAOS") == "true",
    )
    if not allowed_target(target, project) or target["Id"] != request["target_id"]:
        raise ValueError("Target is outside disposable lab")
    if target["Config"]["Labels"]["io.pulsepay.chaos.role"] != SCENARIOS[request["scenario"]][0]:
        raise ValueError("Target role does not match named scenario")
    if not target["State"]["Running"] or target["State"]["Paused"]:
        raise ValueError("Target must begin running and unpaused")
    return {
        "run_id": run_id,
        "scenario": request["scenario"],
        "configuration": config,
        "target": target,
        "created_epoch": time.time(),
        "expires_epoch": time.time() + config["ttl_seconds"],
        "armed": False,
        "revoked": False,
        "injection_started": False,
    }


def save(lease, root=None):
    root = root or AUTHORITY
    private_write(root / lease["run_id"] / "lease.json", lease)
    private_write(root / "active.json", {"run_id": lease["run_id"]})


def watchdog_fresh(lease, root=None):
    stamp = state.read((root or AUTHORITY) / lease["run_id"] / "watchdog-armed.json", {}).get(
        "epoch", 0
    )
    return lease["created_epoch"] <= stamp <= time.time() and time.time() - stamp < 5
