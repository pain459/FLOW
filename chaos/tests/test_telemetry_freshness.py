import json

import httpx
import pytest

from chaos.adapters import telemetry_evidence
from chaos import preflight, state


@pytest.mark.parametrize(
    "delivered,expected", [(True, []), (False, ["NO_RETRIEVABLE_TRACE_SAMPLES_IN_WINDOW"])]
)
def test_trace_delivery_is_polled_with_a_fixed_deadline(monkeypatch, delivered, expected):
    clock = [0.0]
    attempts = []
    monkeypatch.setattr(telemetry_evidence.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        telemetry_evidence.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )

    def request(method):
        if "loki" in str(method.url):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "result": [
                            {
                                "stream": {"service": "api"},
                                "values": [["1", json.dumps({"trace_id": "a" * 32})]],
                            }
                        ]
                    }
                },
            )
        attempts.append(clock[0])
        return (
            httpx.Response(200, json={"batches": [{"scopeSpans": [{"spans": [{"name": "GET"}]}]}]})
            if delivered and clock[0] >= 2
            else httpx.Response(404)
        )

    original = httpx.Client
    monkeypatch.setattr(
        telemetry_evidence.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(request)),
    )
    result = telemetry_evidence.collect(0)
    assert result["missing"] == expected
    assert bool(result["traces"]) == delivered
    assert 2 <= len(attempts) <= 10
    assert clock[0] <= 8


def test_baseline_snapshot_is_captured_after_independent_verification(monkeypatch, tmp_path):
    class Captured(Exception):
        pass

    class Docker:
        def call(self, *args):
            return {}

        def targets(self):
            return []

        def target(self, role):
            return {"Id": "a" * 64, "State": {"Running": True, "Paused": False}}

        def register(self, lease):
            return dict(lease)

    order = []
    monkeypatch.setattr(preflight, "Docker", Docker)
    from types import SimpleNamespace

    monkeypatch.setattr(
        preflight.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * 1024**2)
    )
    monkeypatch.setattr(state, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(state, "CONTROL", tmp_path / "control")
    monkeypatch.setattr(state, "heartbeat", lambda _: None)
    monkeypatch.setattr(state, "read", lambda *args: {"status": "PASS"})
    monkeypatch.setattr(preflight, "load_evidence", lambda: {})
    monkeypatch.setattr(preflight.health_probes, "healthy", lambda _: True)
    monkeypatch.setattr(preflight.observations, "capture", lambda: order.append("capture") or {})
    monkeypatch.setattr(
        preflight.verification, "collect", lambda: order.append("verify") or {"status": "PASS"}
    )

    def publish(*args):
        assert order == ["verify", "capture"]
        raise Captured

    monkeypatch.setattr(preflight.observations, "publish", publish)
    state.EVIDENCE.mkdir()
    with pytest.raises(Captured):
        preflight.preflight({"run_id": "chaos-test", "scenario": "001-api-pause"}, tmp_path)
