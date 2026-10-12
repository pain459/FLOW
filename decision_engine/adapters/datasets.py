"""Only public captures. No imports or paths into privileged experiment evidence."""

import hashlib
import json
from pathlib import Path

from decision_engine.models.observation import from_snapshot

ROOT = Path("/public")

# Opaque curated IDs only. Evaluator labels/split definitions are absent here.
QUALIFIED = {
    "dataset-c37f790d63c9bf30",
    "dataset-bf17f1143b63d124",
    "dataset-c89adf888d98c954",
    "dataset-28acf4c26b3cbbff",
    "dataset-15f86eae6e2fc4bd",
    "dataset-a8fd6635c7163691",
    "dataset-9a9e64643f040d01",
    "dataset-158cc976576f57c6",
}


def catalog(root=ROOT):
    result = []
    for path in sorted(root.glob("*/sequence.jsonl")):
        if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 4 * 1024**2:
            continue
        identifier = "dataset-" + hashlib.sha256(path.parent.name.encode()).hexdigest()[:16]
        result.append(
            {
                "id": identifier,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "kind": "recorded",
                "snapshot_count": len(path.read_text().splitlines()),
            }
        )
    return result


def load(identifier, root=ROOT):
    matches = [
        p
        for p in root.glob("*/sequence.jsonl")
        if "dataset-" + hashlib.sha256(p.parent.name.encode()).hexdigest()[:16] == identifier
    ]
    if len(matches) != 1:
        raise ValueError("unknown dataset")
    path = matches[0]
    if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("unsafe capture")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if not 1 <= len(rows) <= 512:
        raise ValueError("capture sample limit")
    states = [from_snapshot(row).model_dump(mode="json") for row in rows]
    return states, hashlib.sha256(path.read_bytes()).hexdigest()
