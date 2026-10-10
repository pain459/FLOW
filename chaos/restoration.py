"""Idempotent scoped safety rollback; not an experiment sequencer."""

from chaos import state
from chaos.docker_client import Docker
from chaos.policy import allowed_target
from chaos.adapters import toxiproxy
import os
import fcntl
from uuid import uuid4


def restore(lease=None):
    docker = Docker()
    lease = docker.lease() or lease
    if not lease:
        return {"status": "RESTORED", "reason": "NO_ACTIVE_EXPERIMENT"}
    result = {
        "run_id": lease["run_id"],
        "started_at": state.now(),
        "status": "UNKNOWN",
        "errors": [],
    }
    # Closing authorization precedes cleanup, including expiry/abort paths.
    docker.revoke()
    root = state.CONTROL / lease["run_id"]
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = state.lock_file(root / "restore.lock")
    except OSError:
        # A full filesystem must never prevent safety restoration. Injection
        # has already been revoked at the gate; cleanup remains scoped.
        return restore_locked(docker, lease, result)
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if os.getenv("SERVICE_NAME") != "chaos-watchdog":
                return {"status": "RESTORE_BUSY", "run_id": lease["run_id"]}
            # The independent watchdog cannot be blocked by a frozen runner.
            # Authorization is revoked and every cleanup action is scoped.
            return restore_locked(docker, lease, result)
        return restore_locked(docker, lease, result)


def restore_locked(docker, lease, result):
    try:
        state.safe_event("RESTORING")
        helpers = docker.call("GET", "/containers/json?all=true")
        for helper in helpers:
            labels = helper.get("Labels", {})
            if (
                labels.get("io.pulsepay.chaos.run") == lease["run_id"]
                and labels.get("io.pulsepay.chaos.helper") == "true"
            ):
                try:
                    if helper.get("State") == "running":
                        docker.call("POST", f"/containers/{helper['Id']}/stop?t=2")
                    docker.remove(helper["Id"])
                except Exception as exc:
                    # A runner and the watchdog can both restore after a lost
                    # heartbeat. Only verified absence makes concurrent removal
                    # successful; an uninspectable helper remains an error.
                    remaining = docker.call("GET", "/containers/json?all=true")
                    if any(row["Id"] == helper["Id"] for row in remaining):
                        result["errors"].append("helper_cleanup:" + type(exc).__name__)
        target = docker.inspect(lease["target"]["Id"])
        if not allowed_target(target, os.getenv("COMPOSE_PROJECT_NAME", "chaosloop")):
            raise RuntimeError("Frozen target no longer belongs to the lab")
        injected = lease.get("injection_started", False)
        if injected and target["State"]["Paused"]:
            try:
                docker.call("POST", f"/containers/{target['Id']}/unpause")
            except RuntimeError:
                if docker.inspect(target["Id"])["State"]["Paused"]:
                    raise
        if injected and not target["State"]["Running"]:
            try:
                docker.start(target["Id"])
            except RuntimeError:
                if not docker.inspect(target["Id"])["State"]["Running"]:
                    raise
        if injected:
            docker.call(
                "POST",
                f"/containers/{target['Id']}/update",
                json={"RestartPolicy": lease["target"]["HostConfig"]["RestartPolicy"]},
            )
        if lease["scenario"] == "004-api-network-delay" and lease.get("netem_pending"):
            docker.qdisc(target, restore=True, interface=lease["configuration"]["interface"])
            qdisc = docker.qdisc(target, interface=lease["configuration"]["interface"])
            result["qdisc_after"] = qdisc
            if "504d:" in qdisc or "netem" in qdisc:
                raise RuntimeError("Owned netem state remains after rollback")
        result["proxy_restore"] = toxiproxy.restore(lease) if injected else {"not_injected": True}
        after = docker.inspect(target["Id"])
        result["target_after"] = after
        if (
            not after["State"]["Running"]
            or after["State"]["Paused"]
            or after["HostConfig"]["RestartPolicy"]
            != lease["target"]["HostConfig"]["RestartPolicy"]
        ):
            raise RuntimeError("Target state/restart policy was not restored")
        if result["errors"]:
            raise RuntimeError("Some scoped cleanup could not be confirmed")
        result["status"] = "RESTORED"
    except Exception as exc:
        result["errors"].append(type(exc).__name__)
        result["status"] = "MANUAL_ACK_REQUIRED"
    result["finished_at"] = state.now()
    state.safe_write(state.CONTROL / lease["run_id"] / "restoration.json", result)
    path = state.EVIDENCE / lease["run_id"]
    if (path / "checksums.json").exists():
        path = state.EVIDENCE / "recovery" / lease["run_id"]
        state.safe_write(path / ("restoration-" + uuid4().hex + ".json"), result)
    else:
        state.safe_write(path / "restoration.json", result)
    state.safe_event("restoration_result", status=result["status"])
    return result
