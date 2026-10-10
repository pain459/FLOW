import json
from load_generator.controller.lifecycle import atomic_json
from load_generator.controller.resources import ingest_resources


def test_docker_stats_terminal_sequences_do_not_drop_resource_evidence(tmp_path):
    run_id = "load-resource-test"
    path = tmp_path / run_id
    path.mkdir()
    atomic_json(tmp_path / "active.json", {"run_id": run_id})
    row = json.dumps(
        {
            "Name": "lab-api-1",
            "CPUPerc": "20%",
            "MemPerc": "10%",
            "MemUsage": "30MiB / 384MiB",
        }
    )
    ingest_resources(tmp_path, ["\x1b[H" + row + "\n", "\x1b[K\n"])
    assert (
        json.loads((path / "container-resources.jsonl").read_text())["name"]
        == "lab-api-1"
    )
