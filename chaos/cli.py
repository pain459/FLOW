"""Thin native Toolkit entrypoints, safety lease and evidence handoff."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
import yaml
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from chaos import state
from chaos.policy import SCENARIOS
from chaos.preflight import validate, preflight
from chaos.adapters.evidence import finish, recovery_acknowledgement
from chaos.restoration import restore
from chaos.adapters import health_probes, verification
from chaos.docker_client import Docker
from chaos.diagnostics import failure_details


def execution(scenario, inject=False):
    with state.ExperimentLock():
        run_id = (
            "chaos-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        )
        path = state.EVIDENCE / run_id
        path.mkdir(parents=True)
        state.write(state.EVIDENCE / "latest.json", {"run_id": run_id})
        lease = {"run_id": run_id, "scenario": scenario, "armed": False}
        done, child, framework_code = threading.Event(), None, None
        try:
            source, experiment, config = validate(scenario, require_opt_in=inject)
            lease.update(configuration=config, expires_epoch=time.time() + config["ttl_seconds"])
            (path / "experiment.yaml").write_text(source.read_text())
            git_sha = None
            head = Path("/revision/HEAD")
            if head.exists():
                reference = head.read_text().strip()
                git_sha = (
                    (Path("/revision") / reference[5:]).read_text().strip()
                    if reference.startswith("ref: ")
                    else reference
                )
            metadata = {
                "run_id": run_id,
                "scenario": scenario,
                "started_at": state.now(),
                "git_sha": git_sha,
                "scenario_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "configuration": config,
                "runner_image_id": os.getenv("CHAOS_IMAGE_ID"),
                "framework": "chaostoolkit==1.21.4",
                "project": os.getenv("COMPOSE_PROJECT_NAME", "chaosloop"),
            }
            state.write(path / "metadata.json", metadata)
            preflight(lease, path)
            experiment["configuration"] = lease["configuration"]
            (path / "experiment.yaml").write_text(yaml.safe_dump(experiment, sort_keys=False))
            metadata["configuration"] = lease["configuration"]
            metadata["effective_experiment_sha256"] = hashlib.sha256(
                (path / "experiment.yaml").read_bytes()
            ).hexdigest()
            state.write(path / "metadata.json", metadata)
            state.event("BASELINE_CAPTURED")
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "stage": "PREFLIGHT_PASS",
                        "target_id": lease["target"]["Id"],
                        "target_name": lease["target"]["Name"],
                        "exposure_seconds": config["duration_seconds"],
                    }
                ),
                flush=True,
            )
            if not inject:
                state.write(
                    path / "summary.json",
                    {
                        "run_id": run_id,
                        "result": "VALIDATED_NO_INJECTION",
                        "target_id": lease["target"]["Id"],
                        "preflight": "PASS",
                    },
                )
                Docker().release()
                (state.CONTROL / "active.json").unlink(missing_ok=True)
                print(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "preflight": "PASS",
                            "target_id": lease["target"]["Id"],
                            "target_name": lease["target"]["Name"],
                            "injected": False,
                        }
                    )
                )
                return 0

            def pulse():
                while not done.wait(1):
                    state.heartbeat(run_id)

            state.heartbeat(run_id)
            threading.Thread(target=pulse, daemon=True).start()
            deadline = time.monotonic() + 5
            while True:
                try:
                    lease.update(Docker().arm())
                    state.write(state.CONTROL / run_id / "lease.json", lease)
                    break
                except RuntimeError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Independent watchdog did not arm") from None
                    time.sleep(0.1)
            state.event("ARMED")
            command = [
                "chaos",
                "--no-version-check",
                "--log-format",
                "json",
                "--log-file",
                str(path / "framework.log"),
                "run",
                "--rollback-strategy",
                "always",
                "--journal-path",
                str(path / "chaostoolkit-journal.json"),
                str(path / "experiment.yaml"),
            ]
            with (path / "framework-output.jsonl").open("w") as output:
                child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
                while child.poll() is None:
                    if (state.CONTROL / run_id / "abort").exists() or time.time() > lease[
                        "expires_epoch"
                    ]:
                        child.terminate()
                        try:
                            child.wait(10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(5)
                        break
                    time.sleep(0.2)
                framework_code = child.returncode
        except Exception as exc:
            failure = failure_details(exc)
            state.write(path / "failure.json", failure)
            if not lease.get("armed"):
                state.write(
                    path / "summary.json",
                    {
                        "run_id": run_id,
                        "result": "INVALID",
                        **failure,
                    },
                )
                current = Docker().lease()
                if current and current["run_id"] == run_id and not current["armed"]:
                    Docker().release()
                    (state.CONTROL / "active.json").unlink(missing_ok=True)
                print(json.dumps(state.read(path / "summary.json")))
                return 1
        finally:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(5)
        restored = restore(lease)
        summary = finish(lease, restored, framework_code)
        done.set()
        print(
            json.dumps(
                {
                    key: summary[key]
                    for key in (
                        "run_id",
                        "scenario",
                        "result",
                        "integrity",
                        "restoration",
                        "load",
                    )
                }
            )
        )
        return 0 if summary["result"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "list",
            "validate",
            "preflight",
            "run",
            "abort",
            "restore",
            "report",
            "export",
        ),
    )
    parser.add_argument("scenario", nargs="?")
    args = parser.parse_args()
    if args.command == "list":
        try:
            capabilities = Docker().call("GET", "/lab/capabilities")
        except Exception:
            capabilities = {}
        for name, (role, injector, seconds) in SCENARIOS.items():
            print(
                json.dumps(
                    {
                        "scenario": name,
                        "role": role,
                        "injector": injector,
                        "duration_seconds": seconds,
                        "capability": capabilities.get(injector, "UNKNOWN_GATE_NOT_RUNNING"),
                        "database_opt_in": name.startswith("008-"),
                    }
                )
            )
        return 0
    if args.command == "validate":
        validate(args.scenario)
        print(json.dumps({"scenario": args.scenario, "native_validation": "PASS"}))
        return 0
    if args.command in ("preflight", "run"):
        return execution(args.scenario, inject=args.command == "run")
    if args.command == "abort":
        lease = state.active()
        if lease:
            (state.CONTROL / lease["run_id"] / "abort").touch()
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                result = state.read(state.CONTROL / lease["run_id"] / "restoration.json", {})
                if result.get("status") == "RESTORED":
                    print(json.dumps(result))
                    return 0
                time.sleep(0.5)
            raise RuntimeError("Restoration unconfirmed; manual acknowledgement required")
        print(json.dumps({"status": "NO_ACTIVE_EXPERIMENT"}))
        return 0
    if args.command == "restore":
        lease = state.active()
        if lease:
            if (state.EVIDENCE / lease["run_id"] / "checksums.json").exists():
                acknowledgement = recovery_acknowledgement(lease)
                print(json.dumps(acknowledgement))
                return 0 if acknowledgement["status"] == "PASS" else 1
            result = restore(lease)
            healthy = health_probes.recovery()
            summary = finish(lease, result)
            print(json.dumps(summary))
            return 0 if healthy and not summary["manual_ack_required"] else 1
        result = verification.collect()
        print(json.dumps(result))
        return 0 if result["status"] == "PASS" else 1
    identifier = args.scenario
    if identifier in (None, "latest"):
        identifier = state.read(state.EVIDENCE / "latest.json", {}).get("run_id")
    if not identifier or not __import__("re").fullmatch(r"chaos-[a-zA-Z0-9_-]{1,80}", identifier):
        raise ValueError("Missing valid retained experiment ID")
    path = state.EVIDENCE / identifier
    if args.command == "report":
        report = state.read(path / "summary.json")
        print(json.dumps(report, indent=2))
        return 0 if report and report.get("result") in ("PASS", "ABORTED") else 1
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
        archive.add(path, arcname=identifier)
        recovery = state.EVIDENCE / "recovery" / identifier
        if recovery.exists():
            archive.add(recovery, arcname="recovery/" + identifier)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"result": "INVALID", "reason": str(exc)[:300]}))
        raise SystemExit(1) from None
