import hashlib
from pathlib import Path
from chaos import state
from chaos.adapters import verification, observations, health_probes
from chaos.docker_client import Docker
from chaos.adapters import telemetry_evidence
import time
from datetime import datetime

LOAD_REPORTS = Path("/load-reports")


def journal_valid(journal):
    if (
        not isinstance(journal, dict)
        or journal.get("status") != "completed"
        or journal.get("deviated") is not False
    ):
        return False
    hypotheses = journal.get("steady_states", {})
    if any(
        hypotheses.get(epoch, {}).get("steady_state_met") is not True
        for epoch in ("before", "after")
    ):
        return False
    required = {
        "apply-bounded-framework-fault",
        "observe-intentional-fault-exposure",
        "restore-original-environment",
        "independently-verify-post-restoration-recovery",
    }
    runs = journal.get("run", [])
    if {row.get("activity", {}).get("name") for row in runs} != required:
        return False
    if any(row.get("status") != "succeeded" for row in runs):
        return False
    if any(
        row.get("output") is not True
        for row in runs
        if row.get("activity", {}).get("name")
        in {
            "observe-intentional-fault-exposure",
            "independently-verify-post-restoration-recovery",
        }
    ):
        return False
    rollbacks = journal.get("rollbacks", [])
    return bool(rollbacks) and all(row.get("status") == "succeeded" for row in rollbacks)


def injection_confirmed(journal, result):
    return bool(
        result.get("exit_code") == 0
        and isinstance(journal, dict)
        and any(
            row.get("activity", {}).get("name") == "apply-bounded-framework-fault"
            and row.get("status") == "succeeded"
            for row in journal.get("run", [])
        )
    )


def active_load(load_id):
    if not load_id:
        return False
    root = LOAD_REPORTS
    pointer = state.read(root / "active.json", {})
    run = state.read(root / load_id / "state.json", {})
    observation = state.read(root / load_id / "latest-observation.json", {})
    return bool(
        pointer.get("run_id") == load_id
        and run.get("status") == "RUNNING"
        and 0 <= time.time() - observation.get("epoch", 0) < 12
        and observation.get("active_users", 0) > 0
    )


def sustained_load(load_id, since_epoch=None):
    if not active_load(load_id):
        return False
    root = LOAD_REPORTS
    observation = state.read(root / load_id / "latest-observation.json", {})
    measured = observation.get("load", {}).get("measured", {})
    records = state.read(root / load_id / "recent-observations.json", {}, max_bytes=512 * 1024).get(
        "samples", []
    )
    if not records:
        records = state.read(
            root / load_id / "time-series.json", {}, max_bytes=8 * 1024 * 1024
        ).get("samples", [])
    if not records:
        records = state.tail_jsonl(root / load_id / "time-series.jsonl")
    prior = next(
        (
            row.get("load", {}).get("measured", {})
            for row in records
            if row.get("phase") == "running"
            and observation["epoch"] - 35 <= row.get("epoch", 0) <= observation["epoch"] - 15
            and (since_epoch is None or row["epoch"] >= since_epoch)
        ),
        None,
    )
    return bool(
        prior is not None
        and measured.get("http", 0) > prior.get("http", 0)
        and measured.get("confirmed_commits", 0) > prior.get("confirmed_commits", 0)
        and all(
            measured.get("outcomes", {}).get(name, 0) <= prior.get("outcomes", {}).get(name, 0)
            for name in ("infrastructure_failure", "timeout", "contract_error")
        )
    )


def verdict(
    journal,
    pre,
    post,
    restore,
    impact,
    recovery,
    aborted=False,
    telemetry_complete=True,
    load_sustained=True,
    injection_confirmed=True,
):
    if pre.get("status") != "PASS":
        return "INVALID"
    if restore.get("status") != "RESTORED":
        return "INCONCLUSIVE"
    if aborted:
        return "ABORTED" if post.get("status") == "PASS" else "INCONCLUSIVE"
    if not injection_confirmed:
        return "INCONCLUSIVE"
    if not journal or not telemetry_complete or post.get("status") == "UNKNOWN":
        return "INCONCLUSIVE"
    if not journal_valid(journal):
        return "RESILIENCE_FAILURE"
    if (
        post.get("status") != "PASS"
        or not impact.get("observed")
        or recovery.get("status") != "PASS"
    ):
        return "RESILIENCE_FAILURE"
    if not load_sustained:
        return "RESILIENCE_FAILURE"
    return "PASS"


def finish(lease, restore, framework_exit_code=None):
    path = state.EVIDENCE / lease["run_id"]
    if (path / "checksums.json").exists():
        raise RuntimeError("Final evidence is immutable; use an additional recovery report")
    pre = state.read(path / "preflight.json", {"status": "INVALID"})
    post = verification.collect()
    sample = observations.capture()
    telemetry = telemetry_evidence.collect(lease["created_epoch"])
    state.write(path / "telemetry-after.json", telemetry)
    state.write(path / "integrity-after.json", post)
    state.write(path / "metrics-after.json", sample)
    state.write(path / "observation.json", observations.snapshot(sample, lease["run_id"], post))
    try:
        containers = Docker().targets()
    except Exception:
        containers = None
    state.write(path / "service-state-after.json", containers)
    journal = state.read(path / "chaostoolkit-journal.json")
    impact = state.read(path / "impact.json", {})
    recovery = state.read(path / "recovery-verification.json", {})
    aborted = (state.CONTROL / lease["run_id"] / "abort").exists() or (
        state.CONTROL / lease["run_id"] / "watchdog-triggered.json"
    ).exists()
    during = state.read(path / "metrics-during.json", [])
    telemetry_ok = (
        not telemetry["missing"]
        and bool(during)
        and all("PROMETHEUS_UNAVAILABLE_OR_INVALID" not in row["metrics"]["gaps"] for row in during)
    )
    load_id = pre.get("load", {}).get("run_id")
    restored_at = (
        datetime.fromisoformat(restore["finished_at"]).timestamp()
        if restore.get("finished_at")
        else None
    )
    # An idempotent final rollback runs after the recovery probe. Its later
    # timestamp must not discard the actual verified post-restoration window.
    under_load = sustained_load(load_id, recovery.get("productive_since_epoch", restored_at))
    confirmed = injection_confirmed(journal, state.read(path / "injector-result.json", {}))
    result = verdict(
        journal,
        pre,
        post,
        restore,
        impact,
        recovery,
        aborted,
        telemetry_ok,
        under_load,
        confirmed,
    )
    if result == "PASS" and (
        framework_exit_code != 0
        or (state.read(path / "injector-result.json", {}).get("exit_code") != 0)
        or not health_probes.healthy(sample)
    ):
        result = "INCONCLUSIVE"
    load_state = (
        state.read(Path("/load-reports") / str(load_id) / "state.json", {}) if load_id else {}
    )
    preclock = state.read(path / "metadata.json", {})
    summary = {
        "schema_version": 1,
        "run_id": lease["run_id"],
        "scenario": lease["scenario"],
        "result": result,
        "started_at": preclock.get("started_at"),
        "finished_at": state.now(),
        "framework_exit_code": framework_exit_code,
        "integrity": {
            "before": pre.get("integrity", {}).get("status", "UNKNOWN"),
            "after": post.get("status"),
        },
        "restoration": restore.get("status"),
        "impact": impact,
        "recovery": recovery.get("status", "UNKNOWN"),
        "load": {
            "run_id": load_id,
            "profile": (pre.get("load", {}).get("manifest") or {}).get("profile", {}).get("name"),
            "after_state": load_state.get("status", "UNKNOWN"),
            "recovery_condition": "UNDER_SUSTAINED_LOAD"
            if under_load
            else "UNDER_ACTIVE_LOAD_PRODUCTIVITY_UNVERIFIED"
            if active_load(load_id)
            else "AFTER_LOAD_REMOVAL_OR_UNKNOWN",
            "external_control_intervention": False
            if active_load(load_id)
            else True
            if load_state.get("status")
            in {"STOPPING", "STOPPED", "FAILED", "INTERRUPTED", "COMPLETED"}
            else None,
        },
        "missing_observations": sorted(set(sample["metrics"]["gaps"])),
        "journal_available": bool(journal),
        "injection_confirmed": confirmed,
        "manual_ack_required": restore.get("status") != "RESTORED" or post.get("status") != "PASS",
        "artifact_paths": sorted(f.name for f in path.iterdir() if f.is_file()),
    }
    if summary["manual_ack_required"]:
        summary["result"] = "INCONCLUSIVE" if result == "PASS" else result
    state.write(path / "summary.json", summary)
    state.safe_event("FINAL_REPORT", result=summary["result"])
    audit = Docker().call("GET", "/lab/audit")
    (path / "docker-audit.jsonl").write_text("\n".join(audit["records"]) + "\n")
    frozen = Docker().lease() or lease
    injector_state = state.read(path / "injector-state.json", {})
    state.write(
        path / "ground-truth.json",
        {
            "schema_version": 1,
            "privileged": True,
            "run_id": lease["run_id"],
            "scenario": lease["scenario"],
            "configuration": frozen["configuration"],
            "target": {
                "id": frozen["target"]["Id"],
                "name": frozen["target"]["Name"],
                "labels": frozen["target"]["Config"]["Labels"],
            },
            "injection_confirmed": confirmed,
            "injector": injector_state,
            "fault_started_epoch": frozen.get("fault_started_epoch"),
            "independent_fault_deadline_epoch": frozen.get("fault_deadline_epoch"),
            "impact_first_observed_at": impact.get("first_observed_at"),
            "restore_verified_at": recovery.get("verified_at"),
            "source": "gateway-owned lease, injector result, native journal and sampled observations",
            "excluded_from_decision_observations": True,
        },
    )
    if not summary["manual_ack_required"]:
        # The watchdog confirms actual restore independently before the gate
        # will allow the old lease to be released.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                Docker().release()
                (state.CONTROL / "active.json").unlink(missing_ok=True)
                break
            except RuntimeError:
                time.sleep(0.5)
        else:
            summary["manual_ack_required"] = True
            summary["result"] = "INCONCLUSIVE"
            state.write(path / "summary.json", summary)
    (path / "summary.md").write_text(
        f"# {lease['scenario']} — {summary['result']}\n\nRun `{lease['run_id']}`. Independent integrity {summary['integrity']['before']} → {summary['integrity']['after']}. Restoration {summary['restoration']}. Impact observed: {impact.get('observed', 'UNKNOWN')}. Recovery: {summary['recovery']}.\n\n"
        f"Load `{load_id}`: {summary['load']['recovery_condition']}; external control intervention {summary['load']['external_control_intervention']}. Framework journal alone does not establish recovery. Missing observations: {', '.join(summary['missing_observations']) or 'none'}.\n"
    )
    # Index only after final timeline event and release; never rewrite runs.
    digests = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in path.iterdir()
        if f.is_file() and f.name != "checksums.json"
    }
    state.write(path / "checksums.json", digests)
    state.write(state.EVIDENCE / "latest.json", {"run_id": lease["run_id"]})
    return summary


def recovery_acknowledgement(lease):
    """Additional evidence clears a restored lease; it never rewrites history."""
    from chaos.restoration import restore
    from uuid import uuid4

    result = restore(lease)
    deadline = time.monotonic() + 60
    while True:
        sample = observations.capture()
        integrity = verification.collect()
        if health_probes.healthy(sample) and integrity.get("status") == "PASS":
            break
        if time.monotonic() > deadline:
            break
        time.sleep(2)
    acknowledgement = {
        "original_run_id": lease["run_id"],
        "verified_at": state.now(),
        "restoration": result,
        "integrity": integrity,
        "health": sample,
        "status": "PASS"
        if result["status"] == "RESTORED"
        and health_probes.healthy(sample)
        and integrity.get("status") == "PASS"
        else "UNKNOWN",
        "original_experiment_result_unchanged": True,
    }
    path = (
        state.EVIDENCE / "recovery" / lease["run_id"] / ("acknowledgement-" + uuid4().hex + ".json")
    )
    state.write(path, acknowledgement)
    if acknowledgement["status"] == "PASS":
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                Docker().release()
                (state.CONTROL / "active.json").unlink(missing_ok=True)
                return acknowledgement
            except RuntimeError:
                time.sleep(0.5)
        raise RuntimeError("Independent restore acknowledgement not confirmed by gate")
    return acknowledgement
