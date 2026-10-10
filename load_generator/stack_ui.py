"""Persistent Locust UI with idle startup and independently checked finite sessions."""

import os
import time
from pathlib import Path
from uuid import uuid4

from load_generator.controller.lifecycle import RunLock, atomic_json, now, read_json
from load_generator.controller.preflight import Observer, independent_verification
from load_generator.controller.reports import build_summary, write_report
from load_generator.controller.schemas import load_profile
from load_generator.controller.storage import check_report_budget

LOCK = None
STARTED = None
FAILURES = []


def prepare(profile):
    global LOCK, STARTED, FAILURES
    root = Path(os.environ["LOAD_REPORTS"])
    lock = RunLock(root)
    lock.__enter__()
    observer = Observer(os.environ["LOAD_TARGET"])
    try:
        from load_generator.controller.cli import recover_abandoned

        recover_abandoned(root)
        check_report_budget(root, reserve_bytes=32 * 1024**2)
        observer.get("/health/ready")
        health = observer.health()
        if health["status"] != "HEALTHY":
            raise ValueError("Dependencies must be healthy before starting UI traffic")
        accounts, dataset, digest = observer.discover(profile)
        pre = independent_verification()
        if pre["status"] != "PASS":
            raise ValueError("Independent integrity preflight is " + pre["status"])
        run_id = "load-ui-" + uuid4().hex
        path = root / run_id
        path.mkdir()
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": now(),
            "profile": profile.model_dump(),
            "profile_sha256": profile.digest(),
            "accounts": accounts,
            "dataset": dataset,
            "dataset_sha256": digest,
            "traffic_mode": "on_demand",
            "execution_mode": "manual_stack_ui",
            "target": observer.target,
        }
        atomic_json(path / "manifest.json", manifest)
        atomic_json(path / "verifier-pre.json", pre)
        atomic_json(root / "active.json", {"run_id": run_id})
        atomic_json(root / "latest.json", {"run_id": run_id})
        LOCK, STARTED, FAILURES = lock, time.time(), []
        return path, manifest
    except Exception:
        lock.__exit__()
        raise
    finally:
        observer.close()


def finish(path, stats, profile):
    global LOCK
    if LOCK is None:
        return
    observer = Observer(os.environ["LOAD_TARGET"])
    try:
        try:
            observer.cooldown(profile.cooldown_seconds)
        except Exception:
            FAILURES.append("UI_COOLDOWN_INCOMPLETE")
        post = independent_verification()
        atomic_json(path / "verifier-post.json", post)
        manifest = read_json(path / "manifest.json")
        manifest["finished_at"] = now()
        atomic_json(path / "manifest.json", manifest)
        summary = build_summary(
            manifest,
            stats.phases,
            read_json(path / "verifier-pre.json"),
            post,
            max(
                0,
                min(
                    profile.duration_seconds,
                    time.time() - STARTED - profile.warmup_seconds,
                ),
            ),
            FAILURES,
        )
        if summary["result"] == "PASS":
            summary["result"] = "INCOMPLETE"
        summary["failures"].append("MANUAL_UI_SESSION_NOT_A_QUALIFIED_BENCHMARK")
        write_report(path, summary, stats.phases, [], [{"errors": stats.errors}])
        atomic_json(
            path / "state.json",
            {"run_id": manifest["run_id"], "status": "STOPPED", "timestamp": now()},
        )
    finally:
        try:
            observer.close()
            if (path / "summary.json").is_file():
                (Path(os.environ["LOAD_REPORTS"]) / "active.json").unlink(
                    missing_ok=True
                )
        finally:
            LOCK.__exit__()
            LOCK = None


def main():
    root = Path(os.getenv("LOAD_REPORTS", "/reports"))
    root.mkdir(parents=True, exist_ok=True)
    profile = load_profile(
        os.getenv("LOCUST_PROFILE", "nominal"),
        {
            "duration_seconds": int(os.getenv("LOCUST_DURATION_SECONDS", "600")),
            "warmup_seconds": int(os.getenv("LOCUST_WARMUP_SECONDS", "30")),
        },
    )
    idle = Path("/tmp/pulsepay-locust-idle")
    idle.mkdir(exist_ok=True)
    atomic_json(
        idle / "manifest.json", {"profile": profile.model_dump(), "accounts": []}
    )
    os.environ.update(
        LOAD_RUN_DIRECTORY=str(idle), LOAD_MANUAL_UI="true", LOAD_STACK_UI="true"
    )
    os.execvp(
        "locust",
        [
            "locust",
            "-f",
            "load_generator/locustfile.py",
            "--host",
            "http://api:8080",
            "--web-host",
            "0.0.0.0",
            "--web-port",
            "8089",
            "--stop-timeout",
            "15",
        ],
    )


if __name__ == "__main__":
    main()
