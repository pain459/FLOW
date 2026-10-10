"""Finite closed-loop workload with shared clock and bounded worker evidence."""

import os
import time
from pathlib import Path
import gevent
from locust import HttpUser, task, events, LoadTestShape
from locust.runners import MasterRunner
from load_generator.controller.lifecycle import atomic_json, read_json
from load_generator.controller.schemas import Profile, validate_target
from load_generator.workloads.pacing import stage_at
from load_generator.workloads.account_pool import AccountPool
from load_generator.workloads.statistics import Statistics
from load_generator.clients.pulsepay import PulsePayClient

PATH = Path(os.environ["LOAD_RUN_DIRECTORY"])
MANIFEST = read_json(PATH / "manifest.json")
PROFILE = Profile.model_validate(MANIFEST["profile"])
TARGET = validate_target(os.environ.get("LOAD_TARGET", "http://api:8080"))
STATS = Statistics(PATH, "worker-" + str(os.getpid()))
USER_SEQUENCE = 0
MANUAL_UI = os.getenv("LOAD_MANUAL_UI") == "true"
STACK_UI = os.getenv("LOAD_STACK_UI") == "true"
FLUSH = None
WATCHDOG = None
SUPERVISOR = None


@events.init.add_listener
def init(environment, **kwargs):
    if MANUAL_UI:
        from load_generator.workloads.web_ui import install_guard

        install_guard(environment, PROFILE)
    if STACK_UI:
        from flask import request
        from load_generator.controller.telemetry import LoadCollector
        from prometheus_client import CollectorRegistry, start_http_server

        collector = LoadCollector(PROFILE)
        registry = CollectorRegistry()
        registry.register(collector)
        start_http_server(9101, registry=registry)
        environment.pulsepay_collector = collector

        @environment.web_ui.app.before_request
        def prepare_session():
            global PATH, MANIFEST, STATS, USER_SEQUENCE
            if request.path == "/swarm" and request.method == "POST":
                if environment.runner.state not in {"ready", "stopped"}:
                    if environment.runner.state != "running":
                        return {
                            "success": False,
                            "message": "Session is stopping; wait for verification",
                        }, 409
                    return None
                from load_generator.stack_ui import prepare

                try:
                    PATH, MANIFEST = prepare(PROFILE)
                    STATS = Statistics(PATH, "worker-" + str(os.getpid()))
                    USER_SEQUENCE = 0
                except Exception as exc:
                    return {
                        "success": False,
                        "message": type(exc).__name__
                        + ": preflight failed; check funded accounts, integrity, report budget and concurrent runs",
                    }, 409
            return None


@events.test_start.add_listener
def start(environment, **kwargs):
    global FLUSH, WATCHDOG, SUPERVISOR
    STATS.worker = "worker-" + str(os.getpid())
    if not environment.runner.__class__.__name__.startswith("Worker"):
        atomic_json(
            PATH / "clock.json",
            {
                "started_epoch": time.time(),
                "warmup_seconds": PROFILE.warmup_seconds,
                "duration_seconds": PROFILE.duration_seconds,
            },
        )
    if not isinstance(environment.runner, MasterRunner):

        def flush():
            while True:
                STATS.flush(environment.runner.user_count)
                gevent.sleep(1)

                if STACK_UI:
                    collector = environment.pulsepay_collector
                    collector.stats = STATS.phases
                    collector.users = environment.runner.user_count
                    collector.target = environment.runner.target_user_count
                    collector.status = 1

        FLUSH = gevent.spawn(flush)
    if MANUAL_UI:

        def supervise():
            from load_generator.workloads.web_ui import quit_ui

            deadline = time.time() + PROFILE.warmup_seconds + PROFILE.duration_seconds
            next_verify = time.time() + 15
            while environment.runner.state not in {"stopped", "cleanup"}:
                clock = read_json(PATH / "clock.json")
                phase = (
                    "warmup"
                    if time.time() < clock["started_epoch"] + PROFILE.warmup_seconds
                    else "running"
                )
                atomic_json(
                    PATH / "control.json",
                    {
                        "phase": phase,
                        "users": environment.runner.target_user_count,
                        "timestamp_epoch": time.time(),
                    },
                )
                if time.time() >= deadline or (PATH / "cancel").exists():
                    quit_ui(environment)
                    return
                if STACK_UI and time.time() >= next_verify:
                    from load_generator.stack_ui import FAILURES
                    from load_generator.controller.preflight import (
                        independent_verification,
                    )
                    from load_generator.controller.observations import (
                        integrity_requires_stop,
                    )
                    from load_generator.controller.storage import check_report_budget

                    report = independent_verification()
                    environment.pulsepay_collector.verification = report
                    try:
                        check_report_budget(PATH.parent, reserve_bytes=1024**2)
                    except ValueError:
                        FAILURES.append("REPORT_STORAGE_BUDGET_EXCEEDED")
                    if integrity_requires_stop(report) or FAILURES:
                        FAILURES.append("UI_SAFETY_STOP")
                        quit_ui(environment)
                        return
                    next_verify = time.time() + 15
                gevent.sleep(0.25)
            if not STACK_UI:
                quit_ui(environment)

        from load_generator.workloads.web_ui import supervise_safely, quit_ui

        SUPERVISOR = gevent.spawn(supervise_safely, environment, supervise)
        WATCHDOG = gevent.spawn_later(
            PROFILE.warmup_seconds + PROFILE.duration_seconds + 1,
            quit_ui,
            environment,
        )


@events.request.add_listener
def observed(name, response_time, response_length, context, **kwargs):
    STATS.request(
        name,
        context.get("outcome", "contract_error"),
        context.get("status", 0),
        response_time,
        response_length or 0,
        context,
    )


@events.test_stop.add_listener
def stop(environment, **kwargs):
    for greenlet in (SUPERVISOR, WATCHDOG):
        if greenlet and greenlet is not gevent.getcurrent():
            greenlet.kill()
    if FLUSH:
        FLUSH.kill()
    if STACK_UI:
        from load_generator.stack_ui import finish

        try:
            STATS.flush(0)
        finally:
            try:
                finish(PATH, STATS, PROFILE)
            finally:
                environment.pulsepay_collector.users = 0
                environment.pulsepay_collector.status = 0
    elif not isinstance(environment.runner, MasterRunner):
        STATS.flush(0)


class PulsePayUser(HttpUser):
    host = TARGET

    def on_start(self):
        global USER_SEQUENCE
        USER_SEQUENCE += 1
        while not (PATH / "clock.json").exists():
            gevent.sleep(0.05)
        # Scheduling can change user assignment; controlled single-worker plans remain repeatable.
        worker_index = int(getattr(self.environment.runner, "worker_index", 0))
        pool = AccountPool(
            MANIFEST["accounts"],
            PROFILE.seed + worker_index * 100000 + USER_SEQUENCE,
            PROFILE.accounts.hot_account_count
            if PROFILE.accounts.selection == "hot"
            else None,
        )
        self.api = PulsePayClient(self.client, PROFILE, STATS, pool)
        self.started = time.monotonic()

    def wait_time(self):
        think = (
            self.api.pool.random.uniform(
                PROFILE.think_time_ms.min, PROFILE.think_time_ms.max
            )
            / 1000
        )
        control = read_json(PATH / "control.json", {"users": PROFILE.users})
        ceiling = PROFILE.target_operations_per_second
        interval = control["users"] / ceiling if ceiling else 0
        return max(think, interval - (time.monotonic() - self.started))

    @task
    def operation(self):
        self.started = time.monotonic()
        STATS.logical("offered")
        operation = self.api.pool.random.choices(
            list(PROFILE.mix), list(PROFILE.mix.values()), k=1
        )[0]
        if operation.endswith("_read"):
            self.api.read(operation)
        elif operation == "transfer_write":
            self.api.transfer()
        elif operation == "transfer_status":
            self.api.status()
        elif operation == "journey":
            self.api.journey()
        else:
            self.api.rejection()


class PulsePayShape(LoadTestShape):
    abstract = MANUAL_UI
    use_common_options = True

    def tick(self):
        phase, users = stage_at(PROFILE, self.get_run_time())
        if (PATH / "cancel").exists():
            phase, users = "stopped", 0
        old = read_json(PATH / "control.json", {})
        if old.get("phase") != phase or old.get("users") != users:
            control = {"phase": phase, "users": users, "timestamp_epoch": time.time()}
            atomic_json(PATH / "control.json", control)
            with (PATH / "workload-events.jsonl").open("a") as file:
                import json

                file.write(json.dumps(control) + "\n")
        return (users, PROFILE.spawn_rate_users_per_second) if users else None
