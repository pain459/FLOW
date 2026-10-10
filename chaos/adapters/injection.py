"""Native Toolkit action providers for pinned Pumba / scoped Toxiproxy."""

import json
import time
from chaos import state
from chaos.docker_client import Docker, PROJECT
from chaos.policy import PUMBA_IMAGE, SCENARIOS, pumba_command
from chaos.adapters import toxiproxy, observations
from chaos.restoration import restore as restore_lease


def apply(configuration=None):
    lease = state.active()
    if not lease or not lease.get("armed"):
        raise RuntimeError("Experiment was not independently armed")
    state.event("INJECTING")
    if SCENARIOS[lease["scenario"]][1] in ("toxic", "partition"):
        result = toxiproxy.inject(lease)
        state.write(
            state.EVIDENCE / lease["run_id"] / "injector-state.json",
            {"kind": "toxiproxy", "result": result, "applied_at": state.now()},
        )
        return result
    docker = Docker()
    if SCENARIOS[lease["scenario"]][1] == "stop":
        docker.call(
            "POST",
            f"/containers/{lease['target']['Id']}/update",
            json={"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}},
        )
    identifier = docker.helper(PUMBA_IMAGE, pumba_command(lease, PROJECT))
    state.write(
        state.EVIDENCE / lease["run_id"] / "injector-state.json",
        {"kind": "pumba", "container_id": identifier, "applied_at": state.now()},
    )
    state.event("pumba_started", container_id=identifier)
    return {"injector_started": True}


def expected_impact(lease, sample, before, target, stats=None):
    kind = SCENARIOS[lease["scenario"]][1]
    if kind == "pause":
        paused = target["State"]["Paused"]
        if lease["scenario"] == "001-api-pause":
            return paused and sample.get("health") is None
        totals = sample.get("totals") or {}
        initial = (before.get("totals") or {}).get("transfers", 0) - (
            before.get("totals") or {}
        ).get("projections", 0)
        return (
            paused and bool(totals) and totals["transfers"] - totals["projections"] > initial + 10
        )
    if kind == "stop":
        return not target["State"]["Running"] and (
            (sample.get("health") or {})
            .get("dependencies", {})
            .get(
                "postgres" if lease["scenario"] == "008-postgres-outage" else "redis",
                {},
            )
            .get("status")
            != "HEALTHY"
        )
    if kind == "partition":
        return (sample.get("health") or {}).get("dependencies", {}).get("redis", {}).get(
            "status"
        ) != "HEALTHY"
    if kind in ("netem", "toxic"):
        value, prior = (
            sample.get("health_request_latency_ms"),
            before.get("health_request_latency_ms"),
        )
        p95 = sample.get("metrics", {}).get("values", {}).get("api_p95_seconds")
        previous_p95 = before.get("metrics", {}).get("values", {}).get("api_p95_seconds")
        return (value is not None and prior is not None and value > max(100, prior * 2)) or (
            p95 is not None and previous_p95 is not None and p95 > max(0.1, previous_p95 * 2)
        )
    utilization = (stats or {}).get("cpu_utilization")
    return utilization is not None and utilization >= 0.3


def observe(configuration=None):
    lease, docker = state.active(), Docker()
    path = state.EVIDENCE / lease["run_id"]
    before = state.read(path / "baseline.json")
    deadline = time.monotonic() + lease["configuration"]["duration_seconds"] + 4
    rows, detected, first, previous_cpu = [], False, None, None
    state.event("OBSERVING")
    while time.monotonic() < deadline:
        if (state.CONTROL / lease["run_id"] / "abort").exists():
            raise RuntimeError("Experiment aborted")
        sample = observations.capture()
        target = docker.inspect(lease["target"]["Id"])
        try:
            stats = docker.call("GET", f"/containers/{target['Id']}/stats?stream=false") or {}
        except RuntimeError:
            stats = {}
        cpu = stats.get("cpu_stats", {})
        current_cpu = (time.time(), cpu.get("cpu_usage", {}).get("total_usage"))
        utilization = None
        if previous_cpu and current_cpu[1] is not None and previous_cpu[1] is not None:
            utilization = (
                (current_cpu[1] - previous_cpu[1]) / 1e9 / (current_cpu[0] - previous_cpu[0])
            )
        previous_cpu = current_cpu
        sample["container_resources"] = {
            "cpu_utilization": utilization,
            "memory_bytes": stats.get("memory_stats", {}).get("usage"),
            "networks": stats.get("networks"),
        }
        impact = expected_impact(lease, sample, before, target, sample["container_resources"])
        if impact and not detected:
            first = sample["observed_at"]
            state.event("observable_impact_start")
        detected = detected or impact
        rows.append(sample)
        state.write(path / "metrics-during.json", rows)
        state.write(
            path / "impact.json",
            {
                "observed": detected,
                "first_observed_at": first,
                "sampled_at": state.now(),
            },
        )
        snapshot = observations.snapshot(sample, lease["run_id"])
        state.write(path / "observation.json", snapshot)
        with (path / "observations.jsonl").open("a") as file:
            file.write(json.dumps(snapshot) + "\n")
        time.sleep(1)
    injector = state.read(path / "injector-state.json")
    record_injector_result(injector, docker, path)
    state.write(path / "metrics-during.json", rows)
    state.write(
        path / "impact.json",
        {"observed": detected, "first_observed_at": first, "finished_at": state.now()},
    )
    state.event("fault_exposure_end", impact_observed=detected)
    return detected


def record_injector_result(injector, docker, path):
    if injector and injector["kind"] == "pumba":
        identifier = injector["container_id"]
        code = docker.wait(identifier, 10)
        output = docker.logs(identifier)
        (path / "injector-output.jsonl").write_text(output)
        result = {"exit_code": code, "ended_at": state.now()}
    elif (
        injector
        and injector.get("kind") == "toxiproxy"
        and injector.get("result", {}).get("confirmed") is True
    ):
        result = {
            "exit_code": 0,
            "source": "confirmed Toxiproxy HTTP mutation",
            "ended_at": state.now(),
        }
        (path / "injector-output.jsonl").write_text(json.dumps(injector) + "\n")
    else:
        result = {
            "exit_code": None,
            "source": "UNKNOWN",
            "reason": "CONFIRMED_INJECTOR_STATE_MISSING",
            "ended_at": state.now(),
        }
    state.write(path / "injector-result.json", result)
    return result


def restore(configuration=None):
    result = restore_lease()
    if result["status"] != "RESTORED":
        raise RuntimeError("Manual acknowledgement required: restoration could not be confirmed")
    return result
