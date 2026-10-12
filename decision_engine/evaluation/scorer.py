"""Evaluator-only label access. This module is not imported by the investigator."""

import asyncio
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg

from decision_engine.controller.policy import detected
from decision_engine.controller.sessions import replay_start
from decision_engine.adapters.datasets import load

LABELS = {
    "001-api-pause": {"api"},
    "002-worker-pause": {"worker"},
    "003-redis-outage": {"redis"},
    "004-api-network-delay": {"network", "api"},
    "005-db-network-delay": {"postgres", "network"},
    "007-redis-network-partition": {"redis", "network"},
    "008-postgres-outage": {"postgres"},
}


def eligible(label):
    return (
        label.get("result") == "PASS"
        and label.get("injection_confirmed") is True
        and label.get("impact_observed") is True
    )


def verify_seal(folder):
    try:
        seal = json.loads((folder / "checksums.json").read_text())
        files = seal.get("files", seal)
        if not isinstance(files, dict) or not files:
            return False
        return all(
            Path(name).name == name
            and not (folder / name).is_symlink()
            and re.fullmatch(r"[a-f0-9]{64}", digest) is not None
            and hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
            for name, digest in files.items()
        )
    except (OSError, ValueError, TypeError):
        return False


def completed_replay(folder, manifest):
    if not verify_seal(folder) or manifest.get("isolation_version") != "investigator-images-v1":
        return False
    if (manifest.get("replay_plan") or {}).get("version") != "sustained-observation-v1":
        return False
    if manifest.get("state") != "INCONCLUSIVE" and not (
        manifest.get("state") == "ESCALATED"
        and manifest.get("terminal_reason") == "POLICY_ESCALATION"
    ):
        return False
    events = [json.loads(line) for line in (folder / "state-events.jsonl").read_text().splitlines()]
    return not any(e.get("reason") == "CONTROLLER_RESTART" for e in events) and all(
        json.loads(line)["validation_status"] == "VALID"
        for line in (folder / "model-answers.jsonl").read_text().splitlines()
    )


def wilson(success, total):
    if not total:
        return [None, None]
    p, z = success / total, 1.96
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [max(0, center - half), min(1, center + half)]


def score_distribution(p, labels):
    ranked = sorted(p, key=lambda key: (-p[key], key))
    return {
        "top1_correct": ranked[0] in labels,
        "top2_coverage": bool(set(ranked[:2]) & labels),
        "supported_label_mass": sum(v for k, v in p.items() if k in labels),
        "abstained": ranked[0] == "unknown",
        "top1": ranked[0],
    }


def prefault_controls(states, applied):
    if not applied:
        return {"samples": None, "false_alarms": None, "status": "MISSING_INJECTION_TIME"}
    cutoff = datetime.fromisoformat(applied.replace("Z", "+00:00"))
    before = [
        s
        for s in states
        if datetime.fromisoformat(s["observed_at"].replace("Z", "+00:00")) < cutoff
    ]
    return {
        "samples": len(before),
        "false_alarms": sum(detected(before[: i + 1]) for i in range(len(before))),
        "status": "OBSERVED" if before else "NO_PREFAULT_SAMPLES",
    }


def valid_causal_replay(source, exported, plan, actual_hash, recorded_hash):
    return (
        actual_hash == recorded_hash
        and plan == replay_start(source)
        and exported == source[plan["start_index"] : plan["start_index"] + len(exported)]
    )


async def main():
    design = json.loads(Path(__file__).with_name("design-v1.json").read_text())
    uid = uuid4()
    directory = Path("/evaluations") / str(uid)
    directory.mkdir(parents=True, mode=0o700)
    reports = []
    for source_run in design["development_runs"] + design["holdout_runs"]:
        source = Path("/truth") / source_run
        s = json.loads((source / "summary.json").read_text())
        label = {
            "result": s.get("result"),
            "injection_confirmed": s.get("injection_confirmed"),
            "impact_observed": s.get("impact", {}).get("observed"),
        }
        dataset = "dataset-" + hashlib.sha256(source_run.encode()).hexdigest()[:16]
        sessions = []
        excluded_sessions = []
        for candidate in Path("/reports").glob("*/run-manifest.json"):
            manifest = json.loads(candidate.read_text())
            refs = json.loads(candidate.with_name("source-references.json").read_text())
            if refs["dataset_ref"] == dataset:
                if manifest.get("providers") == ["laya-0.4.3"] and completed_replay(
                    candidate.parent, manifest
                ):
                    sessions.append((manifest["created_at"], candidate.parent))
                else:
                    excluded_sessions.append(
                        {
                            "session_id": candidate.parent.name,
                            "reason": "INCOMPLETE_FIXTURE_OR_PRE_ISOLATION_QUALIFICATION",
                        }
                    )
        item = {
            "source_run": source_run,
            "dataset": dataset,
            "split": "holdout" if source_run in design["holdout_runs"] else "development",
            "eligible_fault": eligible(label),
            "ground_truth_hash": hashlib.sha256(
                (source / "ground-truth.json").read_bytes()
            ).hexdigest(),
            "independent_recovery": s.get("recovery", "UNKNOWN"),
            "integrity_after": s.get("integrity", {}).get("after", "UNKNOWN"),
            "exclusion": None,
            "excluded_session_attempts": excluded_sessions,
            "source_seal_valid": verify_seal(source),
        }
        if not item["source_seal_valid"]:
            item["exclusion"] = "SOURCE_EVIDENCE_SEAL_FAILED"
        elif not item["eligible_fault"] or s.get("scenario") not in LABELS:
            item["exclusion"] = "UNCONFIRMED_OR_UNSUPPORTED_FAULT"
        elif not sessions:
            item["exclusion"] = "NO_REAL_PROVIDER_REPLAY"
        else:
            # First completed real replay, not the best or most recently tuned run.
            folder = min(sessions, key=lambda pair: pair[0])[1]
            chosen_manifest = json.loads((folder / "run-manifest.json").read_text())
            plan = chosen_manifest["replay_plan"]
            item["session_id"] = folder.name
            steps = json.loads((folder / "baseline-comparison.json").read_text())
            states = [
                json.loads(line)["state"]
                for line in (folder / "observations.jsonl").read_text().splitlines()
            ]
            selected = 0 if plan["triggered"] else None
            item["valid_decision_count"] = len([step for step in steps if step["laya"]])
            item["replay_plan"] = plan
            truth = json.loads((source / "ground-truth.json").read_text())
            applied = (truth.get("injector") or {}).get("applied_at")
            full_states, actual_hash = load(dataset)
            refs = json.loads((folder / "source-references.json").read_text())
            controls = prefault_controls(full_states, applied)
            item["prefault_controls"] = controls
            item["healthy_prefault_control_samples"] = controls["samples"]
            item["detector_prefault_false_alarms"] = controls["false_alarms"]
            item["causal_source_verified"] = valid_causal_replay(
                full_states, states, plan, actual_hash, refs["source_sha256"]
            )
            if not item["causal_source_verified"]:
                item["exclusion"] = "SOURCE_HASH_OR_CAUSAL_SLICE_MISMATCH"
            elif selected is None:
                item["exclusion"] = "NO_SUSTAINED_INCIDENT_IN_REPLAY_WINDOW"
            elif not steps[selected]["laya"]:
                item["exclusion"] = "MODEL_RESPONSE_UNAVAILABLE"
            else:
                answer = steps[selected]["laya"]["suspected_subsystem"]
                item.update(
                    step=selected,
                    expected_components=sorted(LABELS[s["scenario"]]),
                    laya=score_distribution(answer["probabilities"], LABELS[s["scenario"]]),
                    baseline={
                        "subsystem": steps[selected]["baseline"]["subsystem"],
                        "correct": steps[selected]["baseline"]["subsystem"]
                        in LABELS[s["scenario"]],
                    },
                    model_confidence_uncalibrated=answer["answer_confidence"],
                )
        reports.append(item)
    groups = {}
    for split in ("development", "holdout"):
        rows = [r for r in reports if r["split"] == split]
        applicable = [r for r in rows if r["exclusion"] is None]
        correct = sum(r["laya"]["top1_correct"] for r in applicable)
        groups[split] = {
            "source_runs": len(rows),
            "applicable_runs": len(applicable),
            "excluded_runs": len(rows) - len(applicable),
            "laya_correct": correct,
            "baseline_correct": sum(r["baseline"]["correct"] for r in applicable),
            "laya_top1_accuracy": correct / len(applicable) if applicable else None,
            "laya_95pct_wilson": wilson(correct, len(applicable)),
            "top2_covered": sum(r["laya"]["top2_coverage"] for r in applicable),
            "abstentions": sum(r["laya"]["abstained"] for r in applicable),
        }
    result = {
        "schema_version": 1,
        "evaluation_id": str(uid),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "design": design,
        "groups": groups,
        "items": reports,
        "unauthorized_executed_actions": None,
        "diagnostic_evidence_yield": None,
        "causal_diagnosis_accuracy": None,
        "calibration": {
            "status": "NOT_FITTED",
            "reason": "Small correlated run sample; multiple supported labels; no probability calibration claim",
        },
        "scope": "offline shadow localization hypotheses, not live investigation or remediation",
        "status": "COMPLETE_SHADOW_COMPARISON"
        if all(
            r.get("session_id") and r["source_seal_valid"] and r.get("causal_source_verified")
            for r in reports
        )
        else "INCOMPLETE",
    }
    url = os.environ.get("EVALUATION_DATABASE_URL")
    if url:
        connection = await asyncpg.connect(url, command_timeout=5)
        try:
            result["unauthorized_executed_actions"] = await connection.fetchval(
                "SELECT count(*) FROM decision_intel.tool_calls t JOIN decision_intel.investigation_sessions s ON s.id=t.session_id WHERE s.mode='shadow'"
            )
        finally:
            await connection.close()
    (directory / "evaluation.json").write_text(json.dumps(result, indent=2))
    (directory / "summary.md").write_text(
        "# Paired shadow evaluation\n\n"
        + json.dumps(groups, indent=2)
        + "\n\nEach policy received identical time-available snapshots. Questions and rules were frozen. A preliminary aggregate was viewed before correcting causal replay selection; the nominal holdout is therefore exploratory, and new untouched whole-run holdout data is required. Repeated Redis scenarios are correlated; intervals are descriptive. Excluded incident windows remain listed, and do not count as successful localization. No diagnostic evidence yield, causal certainty or recovery benefit is claimed.\n"
    )
    if url:
        c = await asyncpg.connect(url, command_timeout=5)
        async with c.transaction():
            await c.execute(
                "INSERT INTO decision_evaluation.evaluation_runs VALUES($1,$2,$3,$4,$5,$6,$7,now())",
                uid,
                "readiness-v1",
                "run-heldout-v1",
                "shadow-policy-v1",
                "laya-0.4.3",
                json.dumps(groups),
                result["status"],
            )
            for r in reports:
                if r.get("session_id"):
                    from uuid import UUID

                    await c.execute(
                        "INSERT INTO decision_evaluation.evaluation_items VALUES($1,$2,$3,$4,$5,$6)",
                        uid,
                        UUID(r["session_id"]),
                        r["ground_truth_hash"],
                        json.dumps(
                            {"source": r["source_run"], "expected": r.get("expected_components")}
                        ),
                        json.dumps(r),
                        json.dumps([r["exclusion"]] if r["exclusion"] else []),
                    )
        await c.close()
    print(json.dumps({"evaluation_id": str(uid), "status": result["status"], "groups": groups}))
    if result["status"] == "INCOMPLETE":
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
