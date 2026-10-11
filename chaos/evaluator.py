"""Offline, provenance-linked evaluator labels; never rewrites sealed source runs."""

import argparse
import hashlib
import json
import tarfile
from typing import Any
from datetime import datetime, timezone
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def derive_ground_truth(files):
    checksum_doc = json.loads(files["checksums.json"])
    checksums = checksum_doc.get("files", checksum_doc)
    for name, expected in checksums.items():
        if name not in files or digest(files[name]) != expected:
            raise ValueError("Source hash mismatch: " + name)

    def read(name):
        if name in files and name not in checksums:
            raise ValueError("Unsealed source hash: " + name)
        return json.loads(files[name]) if name in files else {}

    metadata, summary = read("metadata.json"), read("summary.json")
    journal, result = read("chaostoolkit-journal.json"), read("injector-result.json")
    impact, restoration = read("impact.json"), read("restoration.json")
    original_truth = read("ground-truth.json")
    apply: dict[str, Any] = next(
        (
            row
            for row in journal.get("run", [])
            if row.get("activity", {}).get("name") == "apply-bounded-framework-fault"
        ),
        {},
    )
    confirmed = (
        result["exit_code"] == 0 and apply.get("status") == "succeeded"
        if "exit_code" in result and apply
        else None
    )
    identifier = metadata.get("run_id", summary.get("run_id"))
    if not identifier or summary.get("run_id") not in (None, identifier):
        raise ValueError("Inconsistent original run identity")
    state = read("injector-state.json")
    missing = []
    if confirmed is None:
        missing.append("injection_confirmed")
    if not original_truth.get("actual_fault_end"):
        missing.append("actual_fault_end")
    target = original_truth.get("target") or read("preflight.json").get("target")
    if not target:
        before = read("service-state-before.json")
        before = before if isinstance(before, list) else before.get("containers", [])
        identifier_target = read("preflight.json").get("target_id")
        target = next((row for row in before if row.get("Id") == identifier_target), None)
    if not target:
        missing.append("target")
    return {
        "schema_version": 1,
        "privileged": True,
        "run_id": identifier,
        "scenario": metadata.get("scenario", summary.get("scenario")),
        "configuration": metadata.get("configuration"),
        "source_result": summary.get("result"),
        "source_git_sha": metadata.get("git_sha"),
        "target": target,
        "injector": state.get("kind"),
        "injection_confirmed": confirmed,
        "effect_confirmed": impact.get("observed"),
        "injection_action_started_at": apply.get("start"),
        "injection_action_finished_at": apply.get("end"),
        "effect_first_observed_at": impact.get("first_observed_at"),
        "actual_fault_end": original_truth.get("actual_fault_end"),
        "restoration_verified_at": restoration.get("finished_at"),
        "restoration_status": restoration.get("status"),
        "missing_evidence": missing,
        "source_files_sha256": {name: digest(data) for name, data in files.items()},
        "provenance": {
            "scenario": ["metadata.json", "summary.json"],
            "injection_confirmed": ["injector-result.json", "chaostoolkit-journal.json"],
            "effect_confirmed": ["impact.json"],
            "target": ["ground-truth.json", "service-state-before.json", "preflight.json"],
            "restoration_verified_at": ["restoration.json"],
        },
        "interpretation": "Derived evaluator labels only. Missing evidence stays null/UNKNOWN; original result and bytes unchanged.",
    }


def verify_seal(root):
    document = json.loads((root / "checksums.json").read_text())
    records = document.get("files", document)
    for name, expected in records.items():
        path = root / name
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or path.is_symlink()
            or not path.is_file()
            or digest(path.read_bytes()) != expected
        ):
            raise ValueError("Baseline hash mismatch: " + name)
    return len(records)


def curate(baselines, output):
    """Read trusted sealed bundles and create a new, separately sealed evaluator namespace."""
    baselines, output = Path(baselines), Path(output)
    seals = {
        path.parent.name: verify_seal(path.parent)
        for path in sorted(baselines.glob("*/checksums.json"))
    }
    runs, origins = {}, {}
    for path in sorted(baselines.glob("*/runs/chaos-*")):
        if path.is_dir() and not path.is_symlink():
            runs[path.name] = {
                file.name: file.read_bytes()
                for file in path.iterdir()
                if file.is_file() and not file.is_symlink() and file.stat().st_size <= 16 * 1024**2
            }
            origins[path.name] = str(path.relative_to(baselines))
    archive = baselines / "framework-v1/evidence/experiments.tar.gz"
    with tarfile.open(archive) as source:
        for member in source:
            parts = Path(member.name).parts
            if not member.isfile() or member.size > 16 * 1024**2 or ".." in parts:
                continue
            matches = [part for part in parts if part.startswith("chaos-")]
            if not matches:
                continue
            identifier = matches[-1]
            member_index = parts.index(identifier)
            if len(parts[member_index + 1 :]) != 1:
                continue
            stream = source.extractfile(member)
            if stream:
                runs.setdefault(identifier, {})[parts[-1]] = stream.read()
                origins.setdefault(
                    identifier, "framework-v1/evidence/experiments.tar.gz:" + identifier
                )
    derived = []
    output.mkdir(parents=True, exist_ok=False)
    for identifier, files in sorted(runs.items()):
        if not {"summary.json", "metadata.json", "checksums.json"} <= files.keys():
            continue
        label = derive_ground_truth(files)
        directory = output / "ground-truth" / identifier
        directory.mkdir(parents=True)
        (directory / "injected-fault.json").write_text(
            json.dumps(label, indent=2, sort_keys=True) + "\n"
        )
        derived.append(
            {
                "run_id": identifier,
                "scenario": label["scenario"],
                "origin": origins[identifier],
                "original_result": label["source_result"],
                "injection_confirmed": label["injection_confirmed"],
                "effect_confirmed": label["effect_confirmed"],
                "missing_evidence": label["missing_evidence"],
            }
        )
    index = {
        "schema_version": 1,
        "privileged": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_root_seals": seals,
        "runs": derived,
        "original_results_unchanged": True,
    }
    (output / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    hashes = {
        str(file.relative_to(output)): digest(file.read_bytes())
        for file in output.rglob("*")
        if file.is_file()
    }
    (output / "checksums.json").write_text(
        json.dumps({"algorithm": "sha256", "files": hashes}, indent=2, sort_keys=True) + "\n"
    )
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baselines", default="/baselines")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    index = curate(args.baselines, args.output)
    print(
        json.dumps(
            {
                "derived_runs": len(index["runs"]),
                "original_seals": index["original_root_seals"],
                "original_results_unchanged": True,
            }
        )
    )
