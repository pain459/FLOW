"""Local browser adapter to the existing native Chaos Toolkit entrypoints."""

import hmac
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from chaos import state
from chaos.policy import SCENARIOS, MIN_EXPOSURE_SECONDS, MAX_EXPOSURE_SECONDS, bound_configuration
from chaos.preflight import workload_status

UI = Path(__file__).parent / "ui"
IDENTIFIER = re.compile(r"chaos-[a-zA-Z0-9_-]{1,80}")
ARTIFACTS = frozenset(
    {
        "summary.json",
        "metadata.json",
        "preflight.json",
        "integrity-before.json",
        "integrity-after.json",
        "recovery-verification.json",
        "restoration.json",
        "observation.json",
        "impact.json",
        "chaostoolkit-journal.json",
        "checksums.json",
        "ground-truth.json",
        "metrics-before.json",
        "metrics-during.json",
        "metrics-after.json",
    }
)
DESCRIPTIONS = {
    "001-api-pause": "Pause the API; observe availability impact and verified recovery.",
    "002-worker-pause": "Pause event processing; observe backlog growth and catch-up.",
    "003-redis-outage": "Interrupt Redis; verify committed funds and eventual event delivery.",
    "004-api-network-delay": "Add 150 ms network delay to the API; remove only owned netem state.",
    "005-db-network-delay": "Add PostgreSQL latency through deliberately configured Toxiproxy routing.",
    "006-cpu-pressure": "Disabled until actual kernel resource containment can be proven.",
    "007-redis-network-partition": "Interrupt explicitly proxied Redis connections, then restore them.",
    "008-postgres-outage": "Interrupt PostgreSQL; restore the original database and verify financial integrity.",
}


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenario: str | None = Field(None, max_length=80)
    confirm: str | None = Field(None, max_length=80)
    duration_seconds: int | None = Field(None, ge=MIN_EXPOSURE_SECONDS, le=MAX_EXPOSURE_SECONDS)


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.latest = None
        self.children = {}
        self.pending = {}
        self.stopping = threading.Event()

    def start(self, operation, scenario, duration_seconds=None):
        with self.lock:
            if self.stopping.is_set() or (
                operation == "abort" and "abort" in self.pending.values()
            ):
                raise HTTPException(409, "This action is already stopping or pending")
            if operation != "abort" and (
                self.pending or (self.current and self.current["status"] == "RUNNING")
            ):
                raise HTTPException(
                    409, "A browser action is already running; Abort remains available"
                )
            if operation == "abort" and self.current and self.current["status"] == "RUNNING":
                if self.current["operation"] in {"run", "preflight"}:
                    self.current["cancel_requested"] = True
                    current_child = self.children.get(self.current["job_id"])
                    if current_child and current_child.poll() is None:
                        terminate(current_child)
            identifier = "job-" + uuid4().hex
            record = {
                "job_id": identifier,
                "operation": operation,
                "scenario": scenario,
                "status": "RUNNING",
                "started_at": state.now(),
            }
            if scenario:
                config = bound_configuration(
                    scenario, {}, allow_database=True, duration_seconds=duration_seconds
                )
                record.update(
                    duration_seconds=config["duration_seconds"],
                    ttl_seconds=config["ttl_seconds"],
                    duration_override=duration_seconds is not None,
                )
            state.write(state.EVIDENCE / "workbench" / (identifier + ".json"), record)
            if operation != "abort":
                self.current = record
            self.pending[identifier] = operation
            self.latest = record
            threading.Thread(target=self.execute, args=(record,), daemon=True).start()
            return record

    def execute(self, record):
        operations = [record["operation"]]
        if record["operation"] == "abort":
            # Terminated native jobs need existing verified restore/report/release.
            operations.append("restore")
        child = None
        deadline = time.monotonic() + max(240, record.get("ttl_seconds", 120) + 90)
        tail = b""
        try:
            for operation in operations:
                command = [sys.executable, "-m", "chaos.cli", operation]
                if record["scenario"]:
                    command.append(record["scenario"])
                    if (
                        record.get("duration_override", True)
                        and record.get("duration_seconds") is not None
                    ):
                        command.extend(["--duration-seconds", str(record["duration_seconds"])])
                with self.lock:
                    if record.get("cancel_requested") or self.stopping.is_set():
                        raise RuntimeError("Browser action cancelled before native execution")
                # Native CLI owns preflight/lease/TTL/rollback. Never execute browser shell text.
                child = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                with self.lock:
                    self.children[record["job_id"]] = child
                    if self.stopping.is_set() or record.get("cancel_requested"):
                        terminate(child)
                output: list[bytes] = []
                reader = threading.Thread(
                    target=capture_tail, args=(child.stdout, output), daemon=True
                )
                reader.start()
                child.wait(timeout=max(0.001, deadline - time.monotonic()))
                reader.join(timeout=2)
                tail = (tail + (output[0] if output else b""))[-128 * 1024 :]
                if child.returncode:
                    break
            text = tail.decode(errors="replace")
            if child is None:
                raise RuntimeError("Native framework process did not start")
            record.update(
                status="COMPLETED" if child.returncode == 0 else "FAILED",
                exit_code=child.returncode,
                output=text,
                finished_at=state.now(),
            )
        except Exception as exc:
            if child and child.poll() is None:
                terminate(child)
                try:
                    child.wait(5)
                except subprocess.TimeoutExpired:
                    terminate(child, signal.SIGKILL)
                    child.wait(5)
            record.update(status="FAILED", reason=type(exc).__name__, finished_at=state.now())
        finally:
            with self.lock:
                if record.get("cancel_requested"):
                    record.update(status="CANCELLED", finished_at=state.now())
                self.children.pop(record["job_id"], None)
                self.pending.pop(record["job_id"], None)
                if self.current and self.current["job_id"] == record["job_id"]:
                    self.current = record
            state.safe_write(state.EVIDENCE / "workbench" / (record["job_id"] + ".json"), record)

    def stop(self):
        self.stopping.set()
        with self.lock:
            if self.current and self.current["status"] == "RUNNING":
                self.current["cancel_requested"] = True
            for child in self.children.values():
                if child.poll() is None:
                    terminate(child)


def terminate(child, sig=signal.SIGTERM):
    try:
        os.killpg(child.pid, sig)
    except ProcessLookupError:
        pass


def capture_tail(stream, output):
    tail = bytearray()
    while chunk := stream.read(4096):
        tail.extend(chunk)
        del tail[: -128 * 1024]
    output.append(bytes(tail))


def run_path(identifier):
    if not IDENTIFIER.fullmatch(identifier):
        raise HTTPException(404, "Unknown experiment")
    path = state.EVIDENCE / identifier
    if path.is_symlink() or not path.is_dir():
        raise HTTPException(404, "Unknown experiment")
    return path


def create_app():
    from contextlib import asynccontextmanager

    jobs, csrf = Jobs(), secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.stop()

    app = FastAPI(title="PulsePay Chaos Workbench", lifespan=lifespan)
    app.state.jobs = jobs

    @app.middleware("http")
    async def local_boundary(request: Request, next_handler):
        try:
            host = urlsplit("http://" + request.headers.get("host", "")).hostname
        except ValueError:
            host = None
        if host not in {"localhost", "127.0.0.1", "::1", "chaos-workbench"}:
            return JSONResponse({"message": "Local lab host required"}, 403)
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            expected = str(request.base_url).rstrip("/")
            valid = origin == expected and hmac.compare_digest(
                request.headers.get("x-csrf-token", ""), csrf
            )
            valid = valid and hmac.compare_digest(
                request.cookies.get("pulsepay_chaos_session", ""), csrf
            )
            if (
                not valid
                or request.headers.get("content-type", "").split(";")[0] != "application/json"
            ):
                return JSONResponse(
                    {"message": "Matching local Origin, session and CSRF token required"}, 403
                )
            try:
                declared = int(request.headers.get("content-length", "0"))
            except ValueError:
                declared = -1
            if "content-length" not in request.headers or "transfer-encoding" in request.headers:
                return JSONResponse(
                    {"message": "A bounded JSON body with Content-Length is required"}, 413
                )
            if not 0 <= declared <= 4096 or len(await request.body()) > 4096:
                return JSONResponse({"message": "Action body exceeds limit"}, 413)
        response = await next_handler(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "same-origin",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; object-src 'none'",
            }
        )
        return response

    @app.get("/health/live")
    def live():
        return {"status": "HEALTHY", "service": "chaos-workbench"}

    @app.get("/")
    def index():
        return FileResponse(UI / "index.html")

    @app.get("/api/session")
    def session(response: Response):
        response.set_cookie("pulsepay_chaos_session", csrf, httponly=True, samesite="strict")
        return {"token": csrf}

    @app.get("/api/scenarios")
    def scenarios():
        return {
            "items": [
                {
                    "id": name,
                    "target": role,
                    "injector": kind,
                    "duration_seconds": seconds,
                    "min_duration_seconds": MIN_EXPOSURE_SECONDS,
                    "max_duration_seconds": MAX_EXPOSURE_SECONDS,
                    "description": DESCRIPTIONS[name],
                    "enabled": kind != "stress"
                    and (
                        not name.startswith("008-") or os.getenv("ALLOW_DATABASE_CHAOS") == "true"
                    ),
                    "requires_proxy": kind in {"toxic", "partition"},
                    "database_opt_in": name.startswith("008-"),
                }
                for name, (role, kind, seconds) in SCENARIOS.items()
            ]
        }

    @app.get("/api/status")
    def status():
        controls = {}
        with httpx.Client(timeout=1, trust_env=False) as client:
            for name, url in {
                "gateway": "http://docker-gate:2375/health",
                "watchdog": "http://chaos-watchdog:9111/health",
            }.items():
                try:
                    response = client.get(url)
                    controls[name] = "HEALTHY" if response.status_code == 200 else "UNAVAILABLE"
                except httpx.HTTPError:
                    controls[name] = "UNKNOWN"
        active = state.active()
        return {
            "controls": controls,
            "controls_ready": all(v == "HEALTHY" for v in controls.values()),
            "active_experiment": {
                key: active.get(key)
                for key in ("run_id", "scenario", "armed", "revoked", "expires_epoch")
            }
            if active
            else None,
            "browser_job": jobs.latest,
            "workload": workload_status(),
            "observed_at": state.now(),
        }

    @app.post("/api/actions/{operation}", status_code=202)
    def action(operation: str, value: Action):
        if operation not in {"preflight", "run", "abort", "restore"}:
            raise HTTPException(404, "Unknown reviewed action")
        if operation in {"preflight", "run"}:
            if value.scenario not in SCENARIOS:
                raise HTTPException(422, "Select a reviewed scenario")
            if SCENARIOS[value.scenario][1] == "stress":
                raise HTTPException(409, "CPU pressure disabled: kernel containment unverified")
            if operation == "run" and value.confirm != value.scenario:
                raise HTTPException(422, "Explicit selected-scenario confirmation required")
            if value.scenario.startswith("008-") and os.getenv("ALLOW_DATABASE_CHAOS") != "true":
                raise HTTPException(409, "Database interruption is disabled in this deployment")
        elif value.scenario or value.confirm or value.duration_seconds is not None:
            raise HTTPException(422, "Abort/restore accept no scenario or arbitrary arguments")
        return jobs.start(operation, value.scenario, value.duration_seconds)

    @app.get("/api/jobs/{identifier}")
    def job(identifier: str):
        if not re.fullmatch(r"job-[a-zA-Z0-9_-]{1,80}", identifier):
            raise HTTPException(404, "Unknown action")
        value = state.read(
            state.EVIDENCE / "workbench" / (identifier + ".json"), max_bytes=256 * 1024
        )
        if value is None:
            raise HTTPException(404, "Unknown action")
        return value

    @app.get("/api/runs")
    def runs():
        items = []
        for path in sorted(state.EVIDENCE.glob("chaos-*"), reverse=True)[:60]:
            if path.is_symlink() or not path.is_dir():
                continue
            summary = state.read(path / "summary.json", {})
            metadata = state.read(path / "metadata.json", {})
            items.append(
                {
                    "run_id": path.name,
                    "scenario": metadata.get("scenario"),
                    "result": summary.get("result", "IN_PROGRESS_OR_INTERRUPTED"),
                    "started_at": metadata.get("started_at"),
                    "integrity": summary.get("integrity"),
                    "restoration": summary.get("restoration"),
                }
            )
        return {"items": items}

    @app.get("/api/runs/{identifier}")
    def details(identifier: str):
        path = run_path(identifier)
        return {
            "run_id": identifier,
            "summary": state.read(path / "summary.json"),
            "metadata": state.read(path / "metadata.json"),
            "failure": state.read(path / "failure.json"),
            "timeline": state.tail_jsonl(path / "timeline.jsonl", max_bytes=128 * 1024),
            "artifacts": sorted(
                name
                for name in ARTIFACTS
                if (path / name).is_file() and not (path / name).is_symlink()
            ),
        }

    @app.get("/api/runs/{identifier}/artifacts/{name}")
    def artifact(identifier: str, name: str):
        if name not in ARTIFACTS:
            raise HTTPException(404, "Unknown reviewed artifact")
        value = state.read(run_path(identifier) / name)
        if value is None:
            raise HTTPException(404, "Evidence unavailable or exceeds limit")
        return JSONResponse(value)

    app.mount("/assets", StaticFiles(directory=UI, check_dir=False))
    return app


if __name__ == "__main__":
    import uvicorn
    from shared.logging import configure_logging

    configure_logging("chaos-workbench", "INFO")
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=8090,
        limit_concurrency=32,
        backlog=32,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=10,
        log_config=None,
        access_log=False,
    )
