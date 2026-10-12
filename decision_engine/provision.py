"""Explicit first-time immutable checkpoint download; never used by runtime."""

import hashlib
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download
from decision_engine.checkpoint import ARTIFACT_DIGESTS

REVISION = "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67"
WEIGHT_SHA = "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204"


def main():
    directory = Path(
        snapshot_download(
            "convaiinnovations/laya-multilingual",
            revision=REVISION,
            allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
            max_workers=2,
        )
    )
    digest = hashlib.sha256()
    with (directory / "model.safetensors").open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    if digest.hexdigest() != WEIGHT_SHA:
        raise ValueError("checkpoint weight digest mismatch")
    for name, expected in ARTIFACT_DIGESTS.items():
        if (
            name != "model.safetensors"
            and hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected
        ):
            raise ValueError("checkpoint configuration digest mismatch")
    manifest = {
        "model": "convaiinnovations/laya-multilingual",
        "revision": REVISION,
        "weight_sha256": WEIGHT_SHA,
        "files": {
            str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*")
            if p.is_file() and p.name != "model.safetensors"
        },
    }
    Path(os.environ["HF_HOME"], "provisioned.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
