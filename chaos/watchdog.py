"""Independent bounded restoration watchdog, excluded from all injection labels."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from chaos import state
from chaos.restoration import restore
from chaos.docker_client import Docker
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from chaos.policy import SCENARIOS

LAST_TICK = 0.0
EXPERIMENT = Gauge(
    "pulsepay_experiment_status",
    "Privileged experiment markers: idle=0 armed=1 exposure=2 restoring=3 restored=4",
    ["scenario"],
)
for scenario in SCENARIOS:
    EXPERIMENT.labels(scenario).set(0)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(generate_latest())
            return
        self.send_response(200 if time.time() - LAST_TICK < 5 else 503)
        self.end_headers()
        self.wfile.write(b"Independent restoration watchdog")

    def log_message(self, *args):
        pass


def tick():
    docker = Docker()
    lease = docker.lease()
    for scenario in SCENARIOS:
        EXPR = 0
        if lease and lease["scenario"] == scenario:
            EXPR = (
                4
                if lease.get("restored")
                else 3
                if lease["revoked"]
                else 2
                if lease.get("injection_started")
                else 1
                if lease["armed"]
                else 0
            )
        EXPERIMENT.labels(scenario).set(EXPR)
    if not lease:
        return
    if lease.get("restored"):
        return
    root = state.CONTROL / lease["run_id"]
    reason = (
        "OPERATOR_ABORT"
        if (root / "abort").exists()
        else "EXPERIMENT_TTL_EXPIRED"
        if time.time() >= lease["expires_epoch"]
        else "FAULT_LIFETIME_EXCEEDED"
        if time.time() >= lease.get("fault_deadline_epoch", float("inf"))
        else None
    )
    if not reason and not lease["revoked"] and lease["armed"]:
        heartbeat = state.heartbeat_epoch(root)
        if time.time() - heartbeat > 12:
            reason = "RUNNER_HEARTBEAT_LOST"
    if reason or (lease["revoked"] and not lease.get("restored")):
        docker.revoke()
        if reason:
            state.safe_event("watchdog_intervention", reason=reason)
            state.safe_write(
                root / "watchdog-triggered.json", {"reason": reason, "at": state.now()}
            )
        result = restore(lease)
        if result["status"] == "RESTORED":
            docker.call("POST", "/lab/restored", json={})
    elif not lease["revoked"]:
        docker.call("POST", "/lab/watchdog", json={})


def watch():
    global LAST_TICK
    while True:
        LAST_TICK = time.time()
        try:
            tick()
        except Exception as exc:
            # An evidence/filesystem failure cannot kill bounded restoration.
            print(
                '{"event":"watchdog_retry","reason":"' + type(exc).__name__ + '"}',
                flush=True,
            )
        time.sleep(0.5)


if __name__ == "__main__":
    threading.Thread(
        target=lambda: ThreadingHTTPServer(("0.0.0.0", 9111), Health).serve_forever(),
        daemon=True,
    ).start()
    watch()
