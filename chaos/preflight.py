"""Read-only gates and exact scoped target resolution before Toolkit injection."""

import os
import shutil
import subprocess
import time
from pathlib import Path
import httpx
import yaml
import json
from chaos import state
from chaos.diagnostics import PreflightError, failure_details
from chaos.policy import (
    SCENARIOS,
    PROJECTS,
    NETTOOLS_IMAGE,
    CAPABILITY_COMMAND,
    bound_configuration,
    PUMBA_IMAGE,
    pumba_command,
    DRY_RUN_DURATION_SECONDS,
)
from chaos.docker_client import Docker, PROJECT
from chaos.adapters import (
    observations,
    verification,
    health_probes,
    toxiproxy,
    telemetry_evidence,
)

PROVIDERS = {
    ("chaos.adapters.health_probes", "steady"),
    ("chaos.adapters.health_probes", "recovery"),
    ("chaos.adapters.injection", "apply"),
    ("chaos.adapters.injection", "observe"),
    ("chaos.adapters.injection", "restore"),
}
LOAD_REPORTS = Path("/load-reports")


def validate(scenario, require_opt_in=False, duration_seconds=None):
    if scenario not in SCENARIOS:
        raise ValueError("Select a named committed native experiment")
    path = Path("/experiments") / (scenario + ".yaml")
    if not path.exists():
        path = Path("chaos/experiments") / (scenario + ".yaml")
    if path.stat().st_size > 16384:
        raise ValueError("Experiment definition exceeds size ceiling")
    data = yaml.safe_load(path.read_text())
    if not all(
        key in data
        for key in (
            "version",
            "title",
            "description",
            "tags",
            "configuration",
            "steady-state-hypothesis",
            "method",
            "rollbacks",
        )
    ):
        raise ValueError("Native experiment contract incomplete")
    activities = data["steady-state-hypothesis"]["probes"] + data["method"] + data["rollbacks"]
    for activity in activities:
        provider = activity.get("provider", {})
        if (
            provider.get("type") != "python"
            or (provider.get("module"), provider.get("func")) not in PROVIDERS
            or provider.get("arguments")
        ):
            raise ValueError("Only reviewed framework adapter providers are permitted")
    if data.get("controls") or data.get("extensions") or data.get("secrets"):
        raise ValueError("Unreviewed native extensions/controls/secrets are forbidden")
    result = subprocess.run(
        ["chaos", "--no-version-check", "--no-log-file", "validate", str(path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode:
        raise ValueError("Native Chaos Toolkit validation failed: " + result.stdout[-300:])
    configuration = bound_configuration(
        scenario,
        data["configuration"],
        not require_opt_in or os.getenv("ALLOW_DATABASE_CHAOS") == "true",
        duration_seconds=duration_seconds,
    )
    data["configuration"] = configuration
    return path, data, configuration


def load_evidence():
    root = LOAD_REPORTS
    pointer = state.read(root / "active.json")
    if not pointer or not isinstance(pointer.get("run_id"), str):
        raise PreflightError(
            "LOAD_NOT_ACTIVE",
            "Scenario requires existing active steady HTTP load",
            "Start a bounded read/write workload in Locust at port 8089, and wait for warmup and a stable measured window before checking preflight again.",
        )
    identifier = pointer["run_id"]
    if not __import__("re").fullmatch(r"load-[a-zA-Z0-9_-]{1,80}", identifier):
        raise ValueError("Invalid workload pointer")
    path = root / identifier
    run = state.read(path / "state.json", {})
    observation = state.read(path / "latest-observation.json", {})
    if run.get("status") == "WARMUP":
        raise PreflightError(
            "LOAD_WARMING_UP",
            "The workload is still warming up",
            "Keep Locust running; wait for warmup to finish and at least 15 seconds of stable measured reads and writes.",
        )
    if (
        run.get("status") != "RUNNING"
        or time.time() - observation.get("epoch", 0) < 0
        or time.time() - observation.get("epoch", 0) > 12
        or observation.get("active_users", 0) < 1
    ):
        raise PreflightError(
            "LOAD_NOT_PRODUCTIVE",
            "Load is not RUNNING with fresh active-user evidence",
            "Check Locust users and workload status. Start or resume valid traffic, then wait for fresh measured samples.",
        )
    measured = observation.get("load", {}).get("measured", {})
    if measured.get("http", 0) < 100 or measured.get("confirmed_commits", 0) < 20:
        raise PreflightError(
            "LOAD_SAMPLE_MINIMUM_REQUIRED",
            "Load needs at least 100 actual requests and 20 confirmed writes before injection",
            "Keep a mixed read/write Locust workload running until these measured counts are reached; rejected writes do not count.",
        )
    records = state.read(path / "recent-observations.json", {}, max_bytes=512 * 1024).get(
        "samples", []
    )
    if not records:
        records = state.read(path / "time-series.json", {}, max_bytes=8 * 1024 * 1024).get(
            "samples", []
        )
    if not records and (path / "time-series.jsonl").exists():
        records = state.tail_jsonl(path / "time-series.jsonl")
    recent = [
        row
        for row in records
        if row.get("phase") == "running"
        and observation["epoch"] - 35 <= row.get("epoch", 0) <= observation["epoch"] - 15
    ]
    prior = recent[0].get("load", {}).get("measured", {}) if recent else None
    if prior is None:
        raise PreflightError(
            "LOAD_STABILITY_WINDOW_REQUIRED",
            "Need at least 15 seconds of stable measured load evidence",
            "Keep Locust running with successful reads and writes for at least 15 measured seconds, then retry preflight.",
        )
    if measured.get("http", 0) <= prior.get("http", 0) or measured.get(
        "confirmed_commits", 0
    ) <= prior.get("confirmed_commits", 0):
        raise PreflightError(
            "LOAD_NOT_PRODUCTIVE",
            "Recent HTTP reads/writes are not productive",
            "Check Locust for successful requests and confirmed transfers; read-only or rejected traffic cannot qualify this scenario.",
        )
    for name in ("infrastructure_failure", "timeout", "contract_error"):
        if measured.get("outcomes", {}).get(name, 0) > prior.get("outcomes", {}).get(name, 0):
            raise PreflightError(
                "LOAD_BASELINE_ERRORS",
                "Recent measured window was already failing before fault",
                "Resolve the existing request errors and establish a fresh stable read/write window before injecting a fault.",
            )
    return {
        "run_id": identifier,
        "manifest": state.read(path / "manifest.json"),
        "observation": observation,
    }


def workload_status():
    """Read the same mandatory gate without reserving a lease or injecting."""
    try:
        value = load_evidence()
        return {
            "ready": True,
            "code": "LOAD_READY",
            "run_id": value["run_id"],
            "message": "Stable measured HTTP reads and writes are ready for preflight",
            "remediation": "Check the selected scenario preflight before injection.",
        }
    except PreflightError as error:
        return {"ready": False, **failure_details(error)}
    except Exception:
        return {
            "ready": False,
            "code": "LOAD_EVIDENCE_UNKNOWN",
            "message": "Workload evidence is unavailable or invalid",
            "remediation": "Check Locust and its retained workload report; no fault can run without valid load evidence.",
        }


def capability(docker):
    identifier = docker.helper(
        NETTOOLS_IMAGE,
        ["sh", "-c", CAPABILITY_COMMAND],
        {"NetworkMode": "none", "CapAdd": ["NET_ADMIN"]},
    )
    try:
        code = docker.wait(identifier, 10)
        return {
            "supported": code == 0,
            "exit_code": code,
            "output": docker.logs(identifier),
            "scope": "isolated helper loopback only; no lab target mutation",
        }
    finally:
        docker.remove(identifier)


def preflight(lease, path):
    if PROJECT not in PROJECTS:
        raise ValueError("Wrong disposable Compose project")
    size = sum(f.stat().st_size for f in state.EVIDENCE.rglob("*") if f.is_file())
    if size > 256 * 1024**2 or shutil.disk_usage(state.EVIDENCE).free < 64 * 1024**2:
        raise ValueError("Insufficient bounded evidence storage")
    docker = Docker()
    info = docker.call("GET", "/info")
    containers = docker.targets()
    target = docker.target(SCENARIOS[lease["scenario"]][0])
    if not target["State"]["Running"] or target["State"]["Paused"]:
        raise ValueError("Target was not running/unpaused before experiment")
    lease["target"] = target
    frozen = docker.register(lease)
    lease.clear()
    lease.update(frozen)
    state.write(state.CONTROL / lease["run_id"] / "lease.json", lease)
    state.write(state.CONTROL / "active.json", {"run_id": lease["run_id"]})
    state.heartbeat(lease["run_id"])
    load = load_evidence()
    integrity = verification.collect()
    sample = observations.capture()
    baseline = state.read(os.getenv("CHAOS_BASELINE_PATH", "/baselines/workload-v3/baseline.json"))
    if not baseline or baseline.get("result", baseline.get("status")) != "PASS":
        raise ValueError("A qualified healthy reference is required")
    if not health_probes.healthy(sample) or integrity["status"] != "PASS":
        raise ValueError("Healthy dependency/telemetry/independent integrity precondition failed")
    snapshot = observations.publish(sample, lease["run_id"], integrity)
    state.write(path / "observation.json", snapshot)
    with (path / "observations.jsonl").open("a") as stream:
        stream.write(json.dumps(snapshot) + "\n")
    telemetry = telemetry_evidence.collect(time.time() - 60)
    state.write(path / "telemetry-before.json", telemetry)
    if telemetry["missing"]:
        raise ValueError("Fresh log/trace ingestion could not be established")
    kind = SCENARIOS[lease["scenario"]][1]
    supported = {"pause": True, "stop": True, "toxic": True, "partition": True}
    supported["stress"] = False
    if kind == "stress" and info.get("CgroupDriver") == "cgroupfs":
        proof = docker.call("POST", "/lab/cgroup-proof", json={})
        state.write(path / "cpu-scope-proof.json", proof)
        supported["stress"] = proof["supported"]
        lease.update(docker.lease())
    network = capability(docker)
    supported["netem"] = network["supported"]
    state.write(
        path / "capabilities.json",
        {
            "supported": supported,
            "network_probe": network,
            "docker_cgroup_driver": info.get("CgroupDriver"),
        },
    )
    if not supported[kind]:
        raise ValueError("Injector capability unsupported for this backend: " + kind)
    if kind == "netem":
        identifier = docker.helper(
            NETTOOLS_IMAGE,
            ["ip", "-j", "addr"],
            {"NetworkMode": "container:" + target["Id"], "CapAdd": ["NET_ADMIN"]},
        )
        try:
            if docker.wait(identifier, 10):
                raise ValueError("Could not discover application network interface")
            addresses = json.loads(docker.logs(identifier))
            internal = target["NetworkSettings"]["Networks"][PROJECT + "_internal"]["IPAddress"]
            names = [
                row["ifname"]
                for row in addresses
                if any(addr.get("local") == internal for addr in row.get("addr_info", []))
            ]
            if len(names) != 1 or names[0] not in ("eth0", "eth1"):
                raise ValueError("Application internal interface could not be resolved")
            lease.update(docker.call("POST", "/lab/interface", json={"interface": names[0]}))
        finally:
            docker.remove(identifier)
        qdisc = docker.qdisc(target, interface=lease["configuration"]["interface"])
        if (
            "netem" in qdisc
            or "504d:" in qdisc
            or not any(value in qdisc for value in ("noqueue", "fq ", "fq_codel", "pfifo_fast"))
        ):
            raise ValueError("Refuse foreign or stale root qdisc")
        lease["qdisc_before"] = qdisc
    if kind in ("toxic", "partition"):
        name = "api_postgres" if kind == "toxic" else "clients_redis"
        lease["proxy_before"] = toxiproxy.snapshot(name)
        api = docker.target("api")
        routes = api.get("PulsePayDependencyRoutes", {})
        required = "DATABASE_URL" if kind == "toxic" else "REDIS_URL"
        if routes.get(required, {}).get("host") != "toxiproxy":
            raise ValueError("Explicit dependency routing is not enabled")
    else:
        identifier = docker.helper(PUMBA_IMAGE, pumba_command(lease, PROJECT, dry=True))
        try:
            code = docker.wait(identifier, DRY_RUN_DURATION_SECONDS + 10)
            (path / "pumba-dry-run.jsonl").write_text(docker.logs(identifier))
            if code:
                raise ValueError("Pumba dry targeting failed")
        finally:
            docker.remove(identifier)
    with httpx.Client(timeout=3, trust_env=False) as client:
        client.get("http://chaos-watchdog:9111/health").raise_for_status()
        client.get("http://otel-collector:13133/").raise_for_status()
    result = {
        "status": "PASS",
        "at": state.now(),
        "target": target,
        "load": load,
        "integrity": integrity,
        "baseline_reference": baseline,
        "metrics": sample,
        "docker": info,
        "capabilities": supported,
        "network_probe": network,
    }
    state.write(path / "preflight.json", result)
    state.write(path / "baseline.json", sample)
    state.write(path / "metrics-before.json", sample)
    state.write(path / "integrity-before.json", integrity)
    state.write(path / "service-state-before.json", containers)
    state.write(state.CONTROL / lease["run_id"] / "lease.json", lease)
    return result
