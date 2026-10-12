import hashlib
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

from decision_engine.questions.catalog import VERSION
from decision_engine.questions.catalog import questions
from decision_engine.questions.first_response import questions as live_questions


def runtime_provenance(live=False):
    root = Path(__file__).parents[1]
    hashes = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    ceilings = {}
    for name, file in (
        ("cpu_max", "/sys/fs/cgroup/cpu.max"),
        ("memory_max_bytes", "/sys/fs/cgroup/memory.max"),
    ):
        try:
            ceilings[name] = Path(file).read_text().strip()
        except OSError:
            ceilings[name] = None
    return {
        "runtime_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        "question_sha256": hashlib.sha256(
            json.dumps(live_questions() if live else questions(), sort_keys=True).encode()
        ).hexdigest(),
        "architecture": platform.machine(),
        "container_ceilings": ceilings,
    }


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")


def lines(path, rows):
    path.write_text("".join(json.dumps(row, default=str, allow_nan=False) + "\n" for row in rows))


def live_request(decision):
    from decision_engine.inference_input import VERSION, live_input, input_hash, validate_quality

    state = live_input(decision["observation"])
    quality = (decision["policy_decision"] or {}).get("input_quality")
    if decision["validation_status"] == "VALID" and decision["provider_version"] == "laya-0.4.3":
        validate_quality(quality, decision["observation"])
    return {
        "laya_input": state,
        "projection_version": VERSION,
        "input_sha256": input_hash(state),
        "input_quality": quality,
    }


async def export_session(store, uid, reports, source_hash, replay_plan=None):
    directory = Path(reports) / str(uid)
    directory.mkdir(mode=0o750, parents=True, exist_ok=False)
    session = await store.get(uid)
    trace = await store.timeline(uid)
    decisions = trace["decisions"]
    tool_calls = trace.get("tool_calls", [])
    executed = len(tool_calls)
    live = session["mode"] == "live_question"
    providers = sorted({d["provider_version"] for d in decisions if d["provider_version"]})
    manifest = {
        "schema_version": 1,
        "session_id": str(uid),
        "source_revision": os.environ.get("SOURCE_REVISION", "UNKNOWN"),
        "mode": session["mode"],
        "checkpoint_revision": "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67",
        "providers": providers,
        "policy_version": session["policy_version"],
        "question_version": "first-response-v1" if live else VERSION,
        "budget": session["budget"],
        "created_at": session["created_at"],
        "exported_at": datetime.now(timezone.utc),
        "state": session["state"],
        "terminal_reason": session["last_error"],
        "isolation_version": "investigator-images-v1",
        "replay_plan": replay_plan,
        "provenance": runtime_provenance(live),
        "source_revision_kind": "base_commit_plus_runtime_sha256",
        "recovery_status": "UNKNOWN",
        "provisioning_kind": "CI_FIXTURE_PROVIDER"
        if "mock-fixture-v1" in providers
        else "operator_requested_live_observations"
        if live
        else "real_recorded_observations",
        "diagnostic_execution_count": executed,
    }
    write(directory / "run-manifest.json", manifest)
    write(
        directory / "source-references.json",
        {
            "dataset_ref": session["dataset_ref"],
            "source_sha256": source_hash,
            "model_visible_source_ids": False,
        },
    )
    lines(
        directory / "observations.jsonl",
        [
            {"step": d["step"], "state": d["observation"], "payload_hash": d["state_hash"]}
            for d in decisions
        ],
    )
    lines(
        directory / "model-requests.redacted.jsonl",
        [
            {
                "step": d["step"],
                "state": d["observation"],
                "question_version": d["question_set_version"],
                **(live_request(d) if live else {}),
            }
            for d in decisions
        ],
    )
    lines(
        directory / "model-answers.jsonl",
        [
            {
                "step": d["step"],
                "raw": d["raw_answer_redacted"],
                "normalized": d["normalized_answers"],
                "validation_status": d["validation_status"],
                "latency_ms": d["latency_ms"],
                "input_quality": (d["policy_decision"] or {}).get("input_quality"),
            }
            for d in decisions
        ],
    )
    lines(
        directory / "policy-decisions.jsonl",
        [
            {"step": d["step"], "policy": d["policy_decision"], "ranking": d["ranking"]}
            for d in decisions
        ],
    )
    lines(directory / "diagnostic-calls.jsonl", tool_calls)
    lines(directory / "state-events.jsonl", trace["events"])
    write(
        directory / "evidence-index.json",
        {
            "source": "operator_requested_live_observations"
            if live
            else "recorded_sanitized_observations",
            "new_diagnostic_evidence": [],
            "replay_missing_tool_results": not live,
            "model_selected_tool_execution": False,
        },
    )
    write(directory / "conclusion.json", session["conclusion"])
    if live and decisions and decisions[0]["validation_status"] == "VALID":
        from decision_engine.models.live import answer_view

        write(
            directory / "first-response.json",
            answer_view(decisions[0]["observation"], decisions[0]["raw_answer_redacted"]),
        )
    write(
        directory / "baseline-comparison.json",
        [
            {"step": d["step"], "baseline": d["baseline_decision"], "laya": d["normalized_answers"]}
            for d in decisions
        ],
    )
    durations = [d["latency_ms"] for d in decisions if d["latency_ms"] is not None]
    write(
        directory / "metrics.json",
        {
            "decisions": len(decisions),
            "valid_answers": len(durations),
            "diagnostic_steps": executed,
            "unauthorized_executed_actions": executed,
            "inference_ms": durations,
            "diagnostic_evidence_yield": None,
            "recovery_status": "UNKNOWN",
        },
    )
    kind = "Manual live first response" if live else "Shadow investigation"
    context = (
        "An operator requested fresh telemetry and optional correlated call evidence. Laya supplied one ranked hypothesis; it chose no executable tools."
        if live
        else "Recorded observations were replayed in timestamp order."
    )
    (directory / "summary.md").write_text(
        f"# {kind} {uid}\n\nState: {session['state']}. {len(durations)} valid model answers; {executed} model-selected diagnostic records.\n\n{context} Findings are provisional hypotheses. True causal diagnosis and live recovery were not established. Evaluation labels are kept outside this investigator bundle.\n"
    )
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.iterdir()
        if p.is_file()
    }
    write(directory / "checksums.json", {"algorithm": "sha256", "files": hashes})
