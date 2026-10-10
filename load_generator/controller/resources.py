import hashlib
import json
import platform
import time
import math
from pathlib import Path
from load_generator.controller.lifecycle import read_json


def network_counters(value: str) -> dict:
    received, sent, count = 0, 0, 0
    try:
        for line in value.splitlines():
            if ":" not in line:
                continue
            interface, values = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            fields = values.split()
            rx, tx = int(fields[0]), int(fields[8])
            if rx < 0 or tx < 0:
                raise ValueError("Negative interface counter")
            received += rx
            sent += tx
            count += 1
    except (ValueError, IndexError):
        count = 0
    return {
        "network_received_bytes": received if count else None,
        "network_sent_bytes": sent if count else None,
    }


def cgroup():
    root = Path("/sys/fs/cgroup")
    result = {
        "cpu_usage_usec": None,
        "cpu_limit": None,
        "memory_bytes": None,
        "memory_limit_bytes": None,
    }
    try:
        data = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
        result["cpu_usage_usec"] = int(data["usage_usec"])
        quota, period = (root / "cpu.max").read_text().split()
        result["cpu_limit"] = int(quota) / int(period) if quota != "max" else None
        result["memory_bytes"] = int((root / "memory.current").read_text())
        value = (root / "memory.max").read_text().strip()
        result["memory_limit_bytes"] = int(value) if value != "max" else None
    except (OSError, ValueError, KeyError):
        pass
    try:
        result.update(network_counters(Path("/proc/net/dev").read_text()))
    except OSError:
        result.update(network_counters(""))
    return result


def revision():
    try:
        root = Path("/revision")
        head = (root / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        if (root / ref).is_file():
            return (root / ref).read_text().strip()
        for line in (root / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except OSError:
        pass
    return None


def source_digest():
    digest = hashlib.sha256()
    for root in (
        Path("/app/load_generator"),
        Path("/app/verifier"),
        Path("/app/shared"),
    ):
        for file in sorted(root.rglob("*")):
            if file.is_file() and file.suffix in {".py", ".yaml", ".lock"}:
                digest.update(str(file.relative_to("/app")).encode())
                digest.update(file.read_bytes())
    return digest.hexdigest()


def collect_metadata(lines: list[str]) -> dict:
    result = {
        "services": {},
        "machine": {"architecture": platform.machine(), "kernel": platform.release()},
    }
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if "service" in row:
            if row["service"] not in {
                "api",
                "postgres",
                "redis",
                "outbox-relay",
                "event-worker",
                "verifier",
                "prometheus",
                "grafana",
                "load-controller",
            }:
                continue
            result["services"][row["service"]] = {
                key: row.get(key)
                for key in (
                    "running",
                    "image_id",
                    "image_tag",
                    "cpu_limit",
                    "memory_limit_bytes",
                    "health",
                )
            }
            allowed = {
                "DB_POOL_SIZE",
                "DB_TIMEOUT_SECONDS",
                "REQUEST_TIMEOUT_SECONDS",
                "CACHE_TTL_SECONDS",
                "PULSEPAY_CURRENCY",
                "WORKER_POLL_SECONDS",
                "RECLAIM_IDLE_MS",
                "VERIFIER_INTERVAL_SECONDS",
                "SEED_VERSION",
                "SEED_ACCOUNT_COUNT",
                "SEED_BALANCE_MINOR",
            }
            result["services"][row["service"]]["config"] = {
                entry.split("=", 1)[0]: entry.split("=", 1)[1]
                for entry in row.get("config", [])
                if "=" in entry and entry.split("=", 1)[0] in allowed
            }
            if row.get("cpu_limit") is not None:
                result["services"][row["service"]]["cpu_limit"] = row["cpu_limit"] / 1e9
        elif "docker_cpus" in row:
            result["machine"].update(
                {
                    key: row.get(key)
                    for key in (
                        "docker_cpus",
                        "docker_memory_bytes",
                        "docker_version",
                        "architecture",
                        "os",
                    )
                }
            )
    return result


def resource_metric_values(row: dict) -> dict:
    import re

    name = row.get("name", "")
    service = next(
        (
            candidate
            for candidate in (
                "api",
                "postgres",
                "redis",
                "outbox-relay",
                "event-worker",
                "verifier",
            )
            if name.endswith("-" + candidate + "-1")
        ),
        None,
    )
    if not service:
        return {}
    result = {"service": service, "observed_epoch": row.get("observed_epoch")}
    for key in ("cpu_percent", "memory_percent"):
        try:
            result[key] = float(row[key].rstrip("%"))
            if not math.isfinite(result[key]) or result[key] < 0:
                result[key] = None
        except (ValueError, KeyError, AttributeError):
            result[key] = None
    match = re.match(r"([0-9.]+)([kKMGT]?i?B)", row.get("memory", ""))
    if match:
        units = {
            "B": 1,
            "kB": 1000,
            "MB": 1000**2,
            "GB": 1000**3,
            "TB": 1000**4,
            "kiB": 1024,
            "KiB": 1024,
            "KB": 1000,
            "MiB": 1024**2,
            "GiB": 1024**3,
            "TiB": 1024**4,
        }
        result["memory_bytes"] = float(match[1]) * units[match[2]]
    else:
        result["memory_bytes"] = None
    return result


def ingest_resources(root: Path, stream):
    import re

    for line in stream:
        try:
            row = json.loads(re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line))
            active = read_json(root / "active.json")
            if not active:
                continue
            from load_generator.controller.lifecycle import run_path

            path = run_path(root, active["run_id"])
            sample = {
                "observed_epoch": time.time(),
                "name": row.get("Name"),
                "cpu_percent": row.get("CPUPerc"),
                "memory": row.get("MemUsage"),
                "memory_percent": row.get("MemPerc"),
                "network_io": row.get("NetIO"),
                "block_io": row.get("BlockIO"),
                "pids": row.get("PIDs"),
            }
            with (path / "container-resources.jsonl").open("a") as file:
                file.write(json.dumps(sample) + "\n")
        except (ValueError, KeyError, OSError):
            continue
