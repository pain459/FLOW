"""Socket-free finite workload controller; Docker lifecycle belongs to operator scripts."""

import argparse
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from prometheus_client import CollectorRegistry, start_http_server
from load_generator.controller.schemas import load_profile
from load_generator.controller.lifecycle import (
    RunLock,
    Lifecycle,
    atomic_json,
    read_json,
    run_path,
    now,
)
from load_generator.controller.preflight import Observer, independent_verification
from load_generator.controller.reports import (
    merge_workers,
    build_summary,
    write_report,
)
from load_generator.controller.resources import (
    cgroup,
    collect_metadata,
    ingest_resources,
    revision,
    source_digest,
    resource_metric_values,
)
from load_generator.controller.telemetry import prometheus_sample, LoadCollector
from load_generator.controller.storage import check_report_budget


def root_path():
    return Path(os.getenv("LOAD_REPORTS", "/reports"))


def configured(args):
    overrides = {
        key: getattr(args, option)
        for option, key in (
            ("duration", "duration_seconds"),
            ("warmup", "warmup_seconds"),
            ("users", "users"),
            ("rate", "target_operations_per_second"),
            ("workers", "workers"),
        )
        if getattr(args, option, None) is not None
    }
    profile = load_profile(args.profile, overrides)
    if profile.duration_seconds > 3600 and not args.allow_long_run:
        raise ValueError("Multi-hour execution requires --allow-long-run")
    return profile


def safe_shutdown(process, grace=30):
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def recover_abandoned(root):
    """Caller holds the exclusive execution lock; retain crash evidence as interrupted."""
    active = read_json(root / "active.json")
    if not active:
        return
    path = run_path(root, active["run_id"])
    if not read_json(path / "summary.json"):
        manifest = read_json(
            path / "manifest.json",
            {"run_id": active["run_id"], "profile": {"name": "unknown"}},
        )
        stats, workers = merge_workers(path)
        pre = read_json(path / "verifier-pre.json", {"status": "UNKNOWN"})
        post = {"status": "UNKNOWN", "reason": "CONTROLLER_INTERRUPTED", "checks": []}
        atomic_json(path / "verifier-post.json", post)
        summary = build_summary(manifest, stats, pre, post, 0, ["CONTROLLER_INTERRUPTED"], True)
        samples = read_json(path / "time-series.json", {}).get("samples", [])
        write_report(path, summary, stats, samples, workers)
        Lifecycle(path, active["run_id"]).transition("INTERRUPTED", "CONTROLLER_INTERRUPTED")
    (root / "active.json").unlink(missing_ok=True)


def run(args):
    profile = configured(args)
    manual_ui = getattr(args, "web", False)
    if manual_ui and profile.workers != 1:
        raise ValueError("Manual Locust UI uses one worker; use headless for multiple workers")
    root = root_path()
    with RunLock(root):
        recover_abandoned(root)
        check_report_budget(root, reserve_bytes=32 * 1024**2)
        run_id = (
            "load-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        )
        path = run_path(root, run_id)
        path.mkdir()
        state = Lifecycle(path, run_id)
        state.transition("CREATED")
        atomic_json(root / "active.json", {"run_id": run_id})
        atomic_json(root / "latest.json", {"run_id": run_id})
        metadata = read_json(root / "environment.json", {})
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": now(),
            "profile": profile.model_dump(),
            "profile_sha256": profile.digest(),
            "git_sha": revision(),
            "source_tree_sha256": source_digest(),
            "environment": metadata,
            "generator_limits": cgroup(),
            "traffic_mode": "on_demand",
            "target": "http://api:8080",
            "measurement_mode": "closed_loop",
            "execution_mode": "manual_ui" if manual_ui else "headless",
        }
        atomic_json(path / "manifest.json", manifest)
        collector = LoadCollector(profile)
        registry = CollectorRegistry()
        registry.register(collector)
        server, thread = start_http_server(9101, registry=registry)
        observer = Observer(os.getenv("LOAD_TARGET", "http://api:8080"))
        failures, samples, pre, post = (
            [],
            [],
            {"status": "UNKNOWN"},
            {"status": "UNKNOWN"},
        )
        process, interrupted, measured_seconds, snapshot_post = None, False, 0.0, None

        def cancelled(*unused):
            (path / "cancel").touch()

        original_handlers = {
            sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)
        }
        telemetry_samples = 0
        resource_offset = 0
        try:
            state.transition("VALIDATING")
            state.transition("PREFLIGHT")
            pre = independent_verification()
            collector.verification = pre
            atomic_json(path / "verifier-pre.json", pre)
            flight = observer.preflight(profile, metadata, verification=pre)
            initial_prom = prometheus_sample(observer.client)
            if any(
                gap.startswith("scrape:") or gap == "PROMETHEUS_UNAVAILABLE_OR_INVALID"
                for gap in initial_prom["gaps"]
            ):
                raise ValueError("Required Prometheus scrapes are unavailable")
            manifest.update(
                accounts=flight["accounts"],
                dataset=flight["dataset"],
                dataset_sha256=flight["dataset_sha256"],
                preflight_health=flight["health"]["status"],
                snapshot_pre=flight["snapshot"],
                prometheus_pre=initial_prom,
            )
            atomic_json(path / "manifest.json", manifest)
            state.transition("READY")
            env = {**os.environ, "LOAD_RUN_DIRECTORY": str(path)}
            if manual_ui:
                env["LOAD_MANUAL_UI"] = "true"
            command = [
                "locust",
                "-f",
                "load_generator/locustfile.py",
                "--host",
                observer.target,
                "--users",
                str(profile.users),
                "--spawn-rate",
                str(profile.spawn_rate_users_per_second),
                "--stop-timeout",
                "15",
                "--exit-code-on-error",
                "0",
                "--csv",
                str(path / "locust-all"),
                "--csv-full-history",
            ]
            if manual_ui:
                command.extend(["--web-host", "0.0.0.0", "--web-port", "8089"])
            else:
                command.extend(
                    [
                        "--headless",
                        "--run-time",
                        str(profile.warmup_seconds + profile.duration_seconds + 15) + "s",
                    ]
                )
            if profile.workers > 1:
                command.extend(["--processes", str(profile.workers)])
            with (path / "locust.log").open("w") as log:
                process = subprocess.Popen(
                    command, env=env, stdout=log, stderr=log, start_new_session=True
                )
                state.transition("WARMUP")
                collector.status = 1
                deadline = (
                    time.monotonic()
                    + profile.warmup_seconds
                    + profile.duration_seconds
                    + 45
                    + (120 if manual_ui else 0)
                )
                ui_started = False
                next_sample, next_verify, previous_resources = 0.0, 0.0, None
                measured_started, error_windows = None, []
                previous_phase = "warmup"
                while process.poll() is None:
                    current = time.monotonic()
                    control = read_json(path / "control.json", {"phase": "warmup", "users": 0})
                    clock = read_json(path / "clock.json")
                    if clock and measured_started is None:
                        measured_started = clock["started_epoch"] + profile.warmup_seconds
                    if manual_ui and clock and not ui_started:
                        deadline = current + profile.warmup_seconds + profile.duration_seconds + 45
                        ui_started = True
                    if control["phase"] == "running" and previous_phase != "running":
                        state.transition("RUNNING")
                    previous_phase = control["phase"]
                    if (path / "cancel").exists():
                        interrupted = True
                        state.transition("STOPPING", "OPERATOR_CANCELLED")
                        safe_shutdown(process)
                        break
                    if current > deadline:
                        failures.append("GENERATOR_DEADLINE_EXCEEDED")
                        state.transition("STOPPING", failures[-1])
                        safe_shutdown(process)
                        break
                    if current >= next_sample:
                        try:
                            check_report_budget(root, reserve_bytes=1024**2)
                        except ValueError:
                            failures.append("REPORT_STORAGE_BUDGET_EXCEEDED")
                            state.transition("STOPPING", failures[-1])
                            safe_shutdown(process)
                            break
                        totals, workers = merge_workers(path)
                        resources = cgroup()
                        resources["observed_monotonic"] = current
                        if (
                            previous_resources
                            and resources["cpu_usage_usec"] is not None
                            and resources["cpu_limit"]
                        ):
                            resources["cpu_utilization"] = (
                                (resources["cpu_usage_usec"] - previous_resources["cpu_usage_usec"])
                                / 1e6
                                / (current - previous_resources["observed_monotonic"])
                                / resources["cpu_limit"]
                            )
                        previous_resources = resources
                        (
                            collector.stats,
                            collector.users,
                            collector.target,
                            collector.resources,
                        ) = (
                            totals,
                            sum(w["active_users"] for w in workers),
                            control["users"],
                            resources,
                        )
                        prom = prometheus_sample(observer.client)
                        healthy_telemetry = not any(
                            gap.startswith("scrape:") or "PROMETHEUS_" in gap
                            for gap in prom["gaps"]
                        )
                        if (
                            control["phase"] == "running"
                            and healthy_telemetry
                            and all(
                                prom["values"].get(key) is not None
                                for key in (
                                    "api_http_counter",
                                    "db_checked_out",
                                    "outbox_pending",
                                    "worker_pending",
                                    "verifier_status",
                                )
                            )
                        ):
                            telemetry_samples += 1
                        resource_file = path / "container-resources.jsonl"
                        if resource_file.exists():
                            with resource_file.open() as resource_stream:
                                resource_stream.seek(resource_offset)
                                for line in resource_stream:
                                    try:
                                        values = resource_metric_values(json.loads(line))
                                        if values:
                                            collector.container_resources[values["service"]] = (
                                                values
                                            )
                                    except ValueError:
                                        continue
                                resource_offset = resource_stream.tell()
                        previous_measured = (
                            samples[-1].get("load", {}).get("measured", {}).get("http", 0)
                            if samples
                            else 0
                        )
                        collector.measured_rps = (
                            (totals.get("measured", {}).get("http", 0) - previous_measured)
                            / (time.time() - samples[-1]["epoch"])
                            if samples
                            else None
                        )
                        samples.append(
                            {
                                "observed_at": now(),
                                "epoch": time.time(),
                                "phase": control["phase"],
                                "target_users": control["users"],
                                "active_users": collector.users,
                                "generator": resources,
                                "container_resources": dict(collector.container_resources),
                                "load": totals,
                                "prometheus": prom,
                            }
                        )
                        atomic_json(path / "latest-observation.json", samples[-1])
                        atomic_json(
                            path / "recent-observations.json",
                            {
                                "schema_version": 1,
                                "samples": [
                                    {
                                        key: row[key]
                                        for key in ("epoch", "phase", "active_users", "load")
                                    }
                                    for row in samples[-10:]
                                ],
                            },
                        )
                        atomic_json(
                            path / "time-series.json",
                            {"schema_version": 1, "samples": samples},
                        )
                        measured = totals.get("measured", {})
                        outcomes = measured.get("outcomes", {})
                        error_count = sum(
                            outcomes.get(name, 0)
                            for name in (
                                "infrastructure_failure",
                                "timeout",
                                "contract_error",
                            )
                        )
                        error_windows.append((current, measured.get("http", 0), error_count))
                        eligible = [
                            entry
                            for entry in error_windows
                            if current - entry[0] >= profile.safety.stop_on_error_window_seconds
                        ]
                        if eligible:
                            old = eligible[-1]
                            count, errors = (
                                measured.get("http", 0) - old[1],
                                error_count - old[2],
                            )
                            if (
                                count >= 10
                                and errors / count * 100
                                >= profile.safety.stop_on_sustained_error_rate_pct
                            ):
                                failures.append("SUSTAINED_INFRASTRUCTURE_ERROR_RATE")
                        if measured.get("unexpected_business_rejections", 0) > 10:
                            failures.append("DATASET_FUNDING_OR_ACCOUNT_STATE_LIMIT")
                        if clock and time.time() - clock["started_epoch"] > 15:
                            fresh_workers = [
                                w for w in workers if time.time() - w["observed_epoch"] < 10
                            ]
                            if len(fresh_workers) < profile.workers:
                                failures.append("LOCUST_WORKER_MISSING")
                        if failures:
                            safe_shutdown(process)
                            break
                        next_sample = current + 5
                    if current >= next_verify:
                        check = independent_verification()
                        collector.verification = check
                        atomic_json(path / "verifier-latest.json", check)
                        from load_generator.controller.observations import (
                            integrity_requires_stop,
                        )

                        if integrity_requires_stop(check):
                            failures.append("INTEGRITY_DURING_RUN_" + check["status"])
                            safe_shutdown(process)
                            break
                        next_verify = time.monotonic() + 15
                    time.sleep(0.25)
                if process.returncode != 0 and not interrupted:
                    failures.append("LOCUST_EXIT_" + str(process.returncode))
                interrupted = interrupted or (path / "cancel").exists()
                if measured_started:
                    measured_seconds = max(
                        0, min(profile.duration_seconds, time.time() - measured_started)
                    )
                    manifest["measurement_start_utc"] = datetime.fromtimestamp(
                        measured_started, timezone.utc
                    ).isoformat()
                    manifest["measurement_end_utc"] = datetime.fromtimestamp(
                        measured_started + measured_seconds, timezone.utc
                    ).isoformat()
            state.transition("STOPPED")
            collector.status = 2
            state.transition("COOLDOWN")
            snapshot_post = observer.cooldown(profile.cooldown_seconds)
            manifest["snapshot_post"] = snapshot_post
        except Exception as exc:
            failures.append(
                type(exc).__name__ + ":" + str(exc)[:180]
                if isinstance(exc, (ValueError, RuntimeError, TimeoutError))
                else type(exc).__name__
            )
        finally:
            if process:
                safe_shutdown(process)
            state.transition("VERIFYING")
            post = independent_verification()
            collector.verification = post
            atomic_json(path / "verifier-post.json", post)
            if not (path / "verifier-pre.json").exists():
                atomic_json(path / "verifier-pre.json", pre)
            stats, workers = merge_workers(path)
            interrupted = interrupted or (path / "cancel").exists()
            manifest["finished_at"] = now()
            manifest["environment_gaps"] = []
            manifest["prometheus_post"] = prometheus_sample(observer.client)
            measured_samples = [s for s in samples if s["phase"] == "running"]
            manifest["generator_saturation_observed"] = any(
                a["generator"].get("cpu_utilization", 0) >= 0.9
                and b["generator"].get("cpu_utilization", 0) >= 0.9
                for a, b in zip(measured_samples, measured_samples[1:])
            )
            atomic_json(path / "manifest.json", manifest)
            summary = build_summary(
                manifest, stats, pre, post, measured_seconds, failures, interrupted
            )
            summary["timing"].update(
                {
                    key: manifest.get(key)
                    for key in (
                        "measurement_start_utc",
                        "measurement_end_utc",
                        "finished_at",
                    )
                }
            )
            try:
                summary["health"]["postflight"] = observer.health()["status"]
            except Exception:
                summary["health"]["postflight"] = "UNKNOWN"
            summary["load"]["peak_users"] = max([s["active_users"] for s in samples], default=None)
            summary["generator_saturation_observed"] = manifest["generator_saturation_observed"]
            summary["volume"] = {
                "pre": manifest.get("snapshot_pre", {}).get("totals"),
                "post": snapshot_post.get("totals") if snapshot_post else None,
            }
            from load_generator.controller.observations import (
                http_agreement,
                required_evidence_healthy,
            )

            summary["http_agreement"] = http_agreement(samples)
            summary["observation_gaps"] = sorted(
                set(
                    manifest["environment_gaps"]
                    + [gap for sample in samples for gap in sample["prometheus"]["gaps"]]
                )
            )
            summary["generator_limits"] = manifest["generator_limits"]
            summary["generator_network"] = {
                key: {
                    "first_counter": measured_samples[0]["generator"].get(key)
                    if measured_samples
                    else None,
                    "last_counter": measured_samples[-1]["generator"].get(key)
                    if measured_samples
                    else None,
                    "source": "Linux /proc/net/dev; non-loopback interfaces; all generator namespace traffic",
                }
                for key in ("network_received_bytes", "network_sent_bytes")
            }
            summary["resource_peaks"] = {
                service: {
                    key: max(
                        (
                            sample["container_resources"][service][key]
                            for sample in samples
                            if sample["container_resources"].get(service, {}).get(key) is not None
                        ),
                        default=None,
                    )
                    for key in ("cpu_percent", "memory_bytes", "memory_percent")
                }
                for service in collector.container_resources
            }
            if summary["result"] == "PASS" and summary["http_agreement"]["status"] == "UNKNOWN":
                summary["result"] = "INCOMPLETE"
                summary["failures"].append("SERVER_GENERATOR_TELEMETRY_NOT_RECONCILED")
            required_resources = {
                "api",
                "postgres",
                "redis",
                "outbox-relay",
                "event-worker",
            }
            resource_evidence_ok = measured_samples and all(
                required_resources.issubset(
                    {
                        service
                        for service, values in sample["container_resources"].items()
                        if sample["epoch"] - values.get("observed_epoch", 0) < 10
                        and all(
                            values.get(key) is not None
                            for key in ("cpu_percent", "memory_bytes", "memory_percent")
                        )
                    }
                )
                for sample in measured_samples
            )
            if summary["result"] == "PASS" and not resource_evidence_ok:
                summary["result"] = "INCOMPLETE"
                summary["failures"].append("CONTAINER_RESOURCE_OBSERVATIONS_MISSING")
            if summary["result"] == "PASS" and (
                telemetry_samples < 2
                or not required_evidence_healthy(samples, summary["health"]["postflight"])
                or not manifest["generator_limits"].get("cpu_limit")
            ):
                summary["result"] = "INCOMPLETE"
                summary["failures"].append("MEASUREMENT_TELEMETRY_UNAVAILABLE")
            if summary["result"] == "PASS" and manifest["generator_saturation_observed"]:
                summary["result"] = "INCOMPLETE"
                summary["failures"].append("GENERATOR_CPU_SATURATED")
            if summary["result"] == "PASS" and measured_seconds < profile.duration_seconds - 1:
                summary["result"] = "INCOMPLETE"
                summary["failures"].append("MEASUREMENT_TERMINATED_EARLY")
            if manual_ui:
                summary["execution_mode"] = "manual_ui"
                if summary["result"] == "PASS":
                    summary["result"] = "INCOMPLETE"
                    summary["failures"].append("MANUAL_UI_SESSION_NOT_A_QUALIFIED_BENCHMARK")
            state.transition("REPORTING")
            write_report(path, summary, stats, samples, workers)
            baseline = read_json(root / "baseline.json")
            if baseline:
                from load_generator.controller.baseline import comparable_key

                matches = baseline.get("comparison_key") == comparable_key(manifest)
                lines = ["# Baseline comparison", "", "Comparable: " + str(matches), ""]
                if matches:
                    for name, group in (
                        ("achieved_rps", "load"),
                        ("p50_ms", "http"),
                        ("p95_ms", "http"),
                        ("p99_ms", "http"),
                    ):
                        lines.append(
                            f"{name}: observed {summary[group].get(name)}; baseline {baseline['metrics'].get(name)}"
                        )
                else:
                    lines.append(
                        "Profile, initial funding/data volume, runtime settings, images, resource ceilings, traffic mode or machine differ. No regression verdict is inferred."
                    )
                (path / "baseline-comparison.md").write_text("\n".join(lines) + "\n")
            state.transition("COMPLETED" if summary["result"] == "PASS" else summary["result"])
            collector.status = 3 if summary["result"] == "PASS" else 4
            observer.close()
            server.shutdown()
            server.server_close()
            for sig, handler in original_handlers.items():
                signal.signal(sig, handler)
            (root / "active.json").unlink(missing_ok=True)
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "result": summary["result"],
                        "achieved_rps": summary["load"]["achieved_rps"],
                        "valid_reads": summary["http"]["valid_reads"],
                        "confirmed_commits": summary["business"]["confirmed_commits"],
                        "integrity": summary["integrity"],
                        "failures": failures,
                    }
                )
            )
        return {"PASS": 0, "FAILED": 1, "INCOMPLETE": 2, "INTERRUPTED": 130}[summary["result"]]


def main():
    parser = argparse.ArgumentParser(description="PulsePay workload controller")
    parser.add_argument(
        "command",
        choices=[
            "run",
            "preflight",
            "validate",
            "metadata",
            "resource-stream",
            "stop",
            "report",
            "export",
            "baseline",
        ],
    )
    parser.add_argument("--profile", default="smoke")
    parser.add_argument("--duration", type=int)
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--users", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--allow-long-run", action="store_true")
    parser.add_argument("--web", action="store_true", help="Bounded manual Locust UI on port 8089")
    parser.add_argument("--run-id", action="append", default=[])
    args = parser.parse_args()
    root = root_path()
    try:
        if args.command == "run":
            return run(args)
        if args.command == "validate":
            profile = configured(args)
            print(
                json.dumps(
                    {
                        "status": "VALID",
                        "profile": profile.name,
                        "sha256": profile.digest(),
                    }
                )
            )
        elif args.command == "metadata":
            metadata = collect_metadata(sys.stdin.readlines())
            atomic_json(root / "environment.json", metadata)
            print("Captured sanitized Docker environment")
        elif args.command == "resource-stream":
            ingest_resources(root, sys.stdin)
        elif args.command == "preflight":
            profile = configured(args)
            observer = Observer(os.getenv("LOAD_TARGET", "http://api:8080"))
            try:
                data = observer.preflight(
                    profile,
                    read_json(root / "environment.json", {}),
                )
                prom = prometheus_sample(observer.client)
                if any(gap.startswith("scrape:") or "PROMETHEUS_" in gap for gap in prom["gaps"]):
                    raise ValueError("Required Prometheus scrapes are unavailable")
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "funded_accounts": data["dataset"]["funded_count"],
                            "integrity": data["verification"]["status"],
                            "traffic_mode": "on_demand",
                        }
                    )
                )
            finally:
                observer.close()
        elif args.command == "stop":
            active = read_json(root / "active.json")
            if not active:
                raise ValueError("No active workload run")
            path = run_path(root, active["run_id"])
            (path / "cancel").touch()
            deadline = time.monotonic() + 60
            while not read_json(path / "summary.json") and time.monotonic() < deadline:
                try:
                    with RunLock(root):
                        recover_abandoned(root)
                except RuntimeError:
                    pass
                time.sleep(0.5)
            summary = read_json(path / "summary.json")
            if not summary:
                raise TimeoutError("Stop requested; controller has not finished within 60 seconds")
            print(json.dumps({"run_id": active["run_id"], "status": summary["result"]}))
        elif args.command == "export":
            with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
                for path in sorted(root.iterdir()):
                    if path.is_dir() and path.name.startswith("load-"):
                        archive.add(path, arcname=path.name)
        elif args.command == "report":
            try:
                with RunLock(root):
                    recover_abandoned(root)
            except RuntimeError:
                pass
            latest = read_json(root / "latest.json")
            if not latest:
                raise ValueError("No workload report exists")
            path = run_path(root, latest["run_id"])
            summary = read_json(path / "summary.json")
            if not summary:
                state = read_json(path / "state.json", {})
                print(
                    json.dumps(
                        {
                            "run_id": latest["run_id"],
                            "result": "INCOMPLETE",
                            "state": state,
                        }
                    )
                )
                return 2
            print(json.dumps(summary, indent=2))
            return 0 if summary["result"] == "PASS" else 2
        elif args.command == "baseline":
            from load_generator.controller.baseline import qualify

            paths = [run_path(root, run_id) for run_id in args.run_id]
            result = qualify(
                [read_json(path / "manifest.json", {}) for path in paths],
                [read_json(path / "summary.json", {}) for path in paths],
            )
            atomic_json(root / "baseline.json", result)
            print(json.dumps(result, indent=2))
            return 0 if result["result"] == "PASS" else 2
        return 0
    except Exception as exc:
        # Never print transport exceptions/URLs or credentials from environment.
        message = (
            str(exc)[:180]
            if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError))
            else type(exc).__name__
        )
        print(json.dumps({"result": "FAILED", "reason": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
