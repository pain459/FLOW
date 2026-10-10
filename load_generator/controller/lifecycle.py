import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w") as file:
        json.dump(value, file, sort_keys=True, indent=2)
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def run_path(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"load-[a-zA-Z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run identifier")
    return root / run_id


class RunLock:
    def __init__(self, root: Path):
        self.root = root

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = (self.root / ".run.lock").open("a")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError(
                "Another PulsePay load run owns the execution lock"
            ) from None
        return self

    def __exit__(self, *args):
        fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()


class Lifecycle:
    def __init__(self, path: Path, run_id: str):
        self.path, self.run_id = path, run_id
        self.events = []

    def transition(self, status: str, reason: str = ""):
        event = {
            "run_id": self.run_id,
            "status": status,
            "timestamp": now(),
            "reason": reason,
        }
        self.events.append(event)
        atomic_json(self.path / "state.json", event)
        with (self.path / "events.jsonl").open("a") as file:
            file.write(json.dumps(event) + "\n")
