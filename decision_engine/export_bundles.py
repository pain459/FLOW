"""Copy sealed investigator bundles; never overwrite differing evidence."""

import hashlib
import json
import shutil
from pathlib import Path
from uuid import UUID


def export(source=Path("/reports"), destination=Path("/exports")):
    copied = skipped = partial = 0
    for folder in sorted(source.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        UUID(folder.name)
        seal = folder / "checksums.json"
        if not seal.is_file():
            partial += 1
            continue
        files = json.loads(seal.read_text())["files"]
        if not files or any(
            Path(name).name != name
            or (folder / name).is_symlink()
            or hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest
            for name, digest in files.items()
        ):
            raise ValueError("evidence seal mismatch")
        target = destination / folder.name
        if target.exists():
            if (target / "checksums.json").read_bytes() != seal.read_bytes() or any(
                hashlib.sha256((target / name).read_bytes()).hexdigest() != digest
                for name, digest in files.items()
            ):
                raise ValueError("existing export differs")
            skipped += 1
            continue
        target.mkdir(mode=0o750)
        for name in [*files, "checksums.json"]:
            shutil.copyfile(folder / name, target / name)
        copied += 1
    return {"copied": copied, "unchanged": skipped, "partial_retained_on_volume": partial}


if __name__ == "__main__":
    print(json.dumps(export()))
