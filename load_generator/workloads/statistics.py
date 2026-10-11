import os
import time
from pathlib import Path
from load_generator.controller.lifecycle import atomic_json, read_json


class Statistics:
    def __init__(self, path: Path, worker: str):
        self.path, self.worker = path, worker
        self.phases: dict = {}
        self.errors: list[dict] = []
        self.clock = None

    def phase(self):
        if self.clock is None:
            self.clock = read_json(self.path / "clock.json")
        if self.clock is None:
            return "warmup"
        elapsed = time.time() - self.clock["started_epoch"]
        if elapsed < self.clock["warmup_seconds"]:
            return "warmup"
        if elapsed < self.clock["warmup_seconds"] + self.clock["duration_seconds"]:
            return "measured"
        return "cooldown"

    def stats(self, phase=None):
        return self.phases.setdefault(
            phase or self.phase(),
            {
                "http": 0,
                "offered": 0,
                "outcomes": {},
                "operations": {},
                "labels": {},
                "latencies": {},
                "operation_latencies": {},
                "response_bytes": 0,
                "request_body_bytes": 0,
            },
        )

    def logical(self, name: str, count=1, phase=None):
        stats = self.stats(phase)
        stats[name] = stats.get(name, 0) + count

    def request(
        self,
        operation: str,
        outcome: str,
        status: int,
        latency_ms: float,
        size: int,
        context: dict,
    ):
        phase = context["phase"]
        stats = self.stats(phase)
        stats["http"] += 1
        stats["response_bytes"] += size
        stats["request_body_bytes"] += context.get("body_bytes", 0)
        status_class = f"{status // 100}xx" if 100 <= status < 600 else "error"
        label = f"{operation}|{status_class}|{outcome}"
        bucket = str(max(0, min(60000, round(latency_ms))))
        for key, value in (
            ("outcomes", outcome),
            ("operations", operation),
            ("labels", label),
            ("latencies", bucket),
            ("operation_latencies", f"{operation}:{bucket}"),
        ):
            stats[key][value] = stats[key].get(value, 0) + 1
        if outcome in {"success", "replay"}:
            self.logical(
                "valid_transfer_submissions" if operation == "transfer_write" else "valid_reads",
                phase=phase,
            )
        if outcome not in {"success", "replay", "expected_rejection"} and len(self.errors) < 50:
            self.errors.append(
                {
                    "timestamp_epoch": time.time(),
                    "phase": phase,
                    "operation": operation,
                    "outcome": outcome,
                    "status_class": status_class,
                    "request_id": context.get("request_id", ""),
                    "error_class": context.get("error_class", ""),
                }
            )

    def flush(self, active_users: int):
        (self.path / "workers").mkdir(exist_ok=True)
        atomic_json(
            self.path / "workers" / (self.worker + ".json"),
            {
                "worker": self.worker,
                "pid": os.getpid(),
                "observed_epoch": time.time(),
                "active_users": active_users,
                "phases": self.phases,
                "errors": self.errors,
            },
        )
