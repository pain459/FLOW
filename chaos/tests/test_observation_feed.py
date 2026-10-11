import importlib.util
import json
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from chaos.adapters import observations
from chaos import state
from chaos.tests.test_observation_readiness import sample


def test_read_only_feed_exists_without_a_fault_control_interface():
    assert importlib.util.find_spec("chaos.observation_feed") is not None


@pytest.fixture
def client(tmp_path):
    from chaos.observation_feed import create_server

    server = create_server(tmp_path, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", timeout=3) as value:
        yield value, tmp_path
    server.shutdown()
    server.server_close()
    thread.join(2)


def publish(root, identifier="chaos-feed-test"):
    return observations.publish(sample(), identifier, root=root)


def test_reader_has_live_health_but_reports_missing_data_without_fake_pass(client):
    api, _ = client
    assert api.get("/health/live").status_code == 200
    missing = api.get("/api/v1/observations/latest")
    assert missing.status_code == 503
    assert missing.json()["code"] == "OBSERVATIONS_UNAVAILABLE"


def test_separate_namespace_contains_only_sanitized_snapshots_and_replay(client):
    api, root = client
    raw = sample()
    raw.update(
        scenario="008-postgres-outage",
        target="secret-target",
        configuration={"duration_seconds": 60},
    )
    observations.publish(raw, "chaos-feed-test", root=root)
    observations.publish(sample(), "chaos-feed-test", root=root)
    latest = api.get("/api/v1/observations/latest")
    assert latest.status_code == 200
    assert latest.json()["observation"]["schema_version"] == "1.1"
    assert latest.json()["snapshot_age_seconds"] >= 0
    sequence = api.get("/api/v1/observations/chaos-feed-test/sequence?limit=1")
    assert sequence.status_code == 200
    assert len(sequence.json()["observations"]) == 1
    assert "008-postgres-outage" not in sequence.text
    assert "secret-target" not in latest.text
    assert not list(root.rglob("*ground-truth*"))


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs",
        "/api/actions/run",
        "/api/v1/observations/chaos-feed-test/artifacts/ground-truth.json",
        "/metrics",
        "/api/v1/query?query=pulsepay_experiment_status",
    ],
)
def test_reader_never_serves_operator_artifacts_metrics_or_actions(client, path):
    api, root = client
    publish(root)
    assert api.get(path).status_code == 404
    assert api.post(path, json={"scenario": "008-postgres-outage"}).status_code == 405


@pytest.mark.parametrize(
    "suffix", ["?limit=0", "?limit=513", "?limit=bad", "?command=stop", "?limit=2&limit=3"]
)
def test_replay_rejects_unbounded_or_unsupported_parameters(client, suffix):
    api, root = client
    publish(root)
    assert api.get("/api/v1/observations/chaos-feed-test/sequence" + suffix).status_code == 400


def test_reader_refuses_privileged_fields_even_if_file_is_planted(client):
    api, root = client
    publish(root)
    path = root / "chaos-feed-test" / "latest.json"
    value = json.loads(path.read_text())
    value["database"]["scenario"] = "008-postgres-outage"
    state.write(path, value)
    response = api.get("/api/v1/observations/latest")
    assert response.status_code == 503
    assert "008-postgres-outage" not in response.text


def test_reader_rejects_symlinked_run_directory(client, tmp_path):
    api, root = client
    private = tmp_path / "private"
    private.mkdir()
    state.write(private / "latest.json", observations.snapshot(sample(), "chaos-feed-test"))
    (root / "chaos-feed-test").symlink_to(private, target_is_directory=True)
    state.write(root / "latest.json", {"run_id": "chaos-feed-test"})
    assert api.get("/api/v1/observations/latest").status_code == 503


def test_publisher_refuses_a_symlinked_namespace(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    root = tmp_path / "public"
    root.mkdir()
    (root / "chaos-feed-test").symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe"):
        publish(root)
    assert not list(private.iterdir())


def test_publisher_refuses_symlinked_root_before_creating_any_directory(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    root = tmp_path / "public"
    root.symlink_to(private, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe"):
        publish(root)
    assert not list(private.iterdir())


@pytest.mark.parametrize(
    "contradiction",
    ["missing_stamp", "future_stamp", "stale_pass", "stale_value", "false_complete"],
)
def test_reader_rejects_contradictory_quality_claims(client, contradiction):
    api, root = client
    publish(root)
    path = root / "chaos-feed-test" / "latest.json"
    value = json.loads(path.read_text())
    source = value["freshness"]["sources"]["api"]
    if contradiction == "missing_stamp":
        source.update(observed_at=None, age_seconds=None)
    elif contradiction == "future_stamp":
        source.update(
            observed_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            age_seconds=0,
        )
    elif contradiction == "stale_pass":
        value["integrity"]["status"] = "PASS"
    elif contradiction == "stale_value":
        source.update(
            observed_at=(
                datetime.fromisoformat(value["observation_time"]) - timedelta(seconds=40)
            ).isoformat(),
            age_seconds=40,
            status="STALE",
        )
    else:
        value["data_quality"] = "COMPLETE"
    state.write(path, value)
    assert api.get("/api/v1/observations/latest").status_code == 503


@pytest.mark.parametrize("fixture", ["oversized", "file_symlink"])
def test_reader_refuses_unsafe_snapshot_files(client, fixture, tmp_path):
    from chaos.observation_contract import MAX_BYTES

    api, root = client
    publish(root)
    path = root / "chaos-feed-test" / "latest.json"
    if fixture == "oversized":
        path.write_bytes(b" " * (MAX_BYTES + 1))
    else:
        private = tmp_path / "private.json"
        private.write_text(path.read_text())
        path.unlink()
        path.symlink_to(private)
    assert api.get("/api/v1/observations/latest").status_code == 503
