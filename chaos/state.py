import fcntl
import json
import os
import re
import time
import sys
import stat
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CONTROL = Path(os.getenv("CHAOS_CONTROL", "/control"))
EVIDENCE = Path(os.getenv("CHAOS_EVIDENCE", "/evidence"))
# Gate and non-root runner/watchdog share only these mailboxes/evidence. The
# authority volume has stricter explicit ownership and is absent from runner.
os.umask(0o007)


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path, default=None, *, max_bytes=4 * 1024 * 1024):
    try:
        # Shared mailboxes are untrusted. Never follow a final symlink, block
        # on a FIFO/device, or allocate unbounded data before restoration.
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                return default
            payload = file.read(max_bytes + 1)
        if len(payload) > max_bytes:
            return default
        return json.loads(payload)
    except (OSError, ValueError, RecursionError):
        return default


def heartbeat_epoch(root):
    payload = read(Path(root) / "heartbeat.json", {}, max_bytes=4096)
    epoch = payload.get("epoch") if isinstance(payload, dict) else None
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
        return 0.0
    return epoch


def tail_jsonl(path, max_bytes=512 * 1024):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                return []
            offset = max(0, info.st_size - max_bytes)
            file.seek(offset)
            lines = file.read(max_bytes).splitlines()
        if offset:
            lines = lines[1:]
        return [json.loads(line) for line in lines if line]
    except (OSError, ValueError, RecursionError):
        return []


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as file:
            os.fchmod(file.fileno(), 0o660)
            json.dump(value, file, indent=2, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def active():
    pointer = read(CONTROL / "active.json", max_bytes=4096)
    if not isinstance(pointer, dict):
        return None
    run_id = pointer.get("run_id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"chaos-[a-zA-Z0-9_-]{1,80}", run_id):
        return None
    lease = read(CONTROL / run_id / "lease.json", max_bytes=64 * 1024)
    if not isinstance(lease, dict) or lease.get("run_id") != run_id:
        return None
    return lease


def event(name, **details):
    lease = active()
    if lease:
        path = EVIDENCE / lease["run_id"] / "timeline.jsonl"
        if (path.parent / "checksums.json").exists():
            path = EVIDENCE / "recovery" / lease["run_id"] / "timeline.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o660
        )
        with os.fdopen(descriptor, "a") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                raise ValueError("Unsafe or oversized evidence timeline")
            file.write(json.dumps({"timestamp": now(), "event": name, **details}) + "\n")


def safe_event(name, **details):
    try:
        event(name, **details)
    except (OSError, ValueError):
        print(
            json.dumps({"event": "evidence_write_failed", "original_event": name}),
            file=sys.stderr,
        )


def safe_write(path, value):
    try:
        write(path, value)
    except OSError:
        print(
            json.dumps({"event": "evidence_write_failed", "file": Path(path).name}),
            file=sys.stderr,
        )


def lock_file(path):
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, 0o660
    )
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise OSError("Unsafe shared lock file")
    return os.fdopen(descriptor, "a+")


class ExperimentLock:
    def __enter__(self):
        CONTROL.mkdir(parents=True, exist_ok=True)
        self.file = lock_file(CONTROL / ".experiment.lock")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if active():
                raise RuntimeError("Previous experiment still requires verified restoration")
        except (BlockingIOError, RuntimeError):
            self.file.close()
            raise RuntimeError("Another experiment holds the exclusive lab lease") from None
        return self

    def __exit__(self, *args):
        fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()


def heartbeat(run_id):
    write(CONTROL / run_id / "heartbeat.json", {"epoch": time.time()})
