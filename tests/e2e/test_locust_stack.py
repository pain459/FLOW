"""Explicit opt-in real UI acceptance; normal tests never generate lab traffic."""

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("LOCUST_UI_TEST") != "true", reason="explicit live Locust acceptance only"
)


def test_idle_start_stop_restart_and_input_guards():
    with httpx.Client(timeout=60, trust_env=False) as client:
        base = "http://locust:8089"
        assert client.get(base).status_code == 200
        initial = client.get("http://api:8080/api/v1/dashboard").json()["totals"]["transfers"]
        time.sleep(5)
        assert (
            client.get("http://api:8080/api/v1/dashboard").json()["totals"]["transfers"] == initial
        )
        values = {"user_count": "10", "spawn_rate": "10", "host": "http://api:8080"}
        assert (
            client.post(base + "/swarm", data={**values, "host": "https://example.com"}).status_code
            == 400
        )
        assert client.post(base + "/swarm", data={**values, "user_count": "151"}).status_code == 400
        for duration in (12, 8):
            response = client.post(base + "/swarm", data=values)
            assert response.status_code == 200, response.text
            time.sleep(duration)
            stats = client.get(base + "/stats/requests").json()
            assert stats["state"] == "running"
            assert (
                sum(row["num_requests"] for row in stats["stats"] if row["name"] != "Aggregated")
                >= 100
            )
            assert (
                client.get("http://api:8080/api/v1/dashboard").json()["totals"]["transfers"]
                > initial
            )
            client.get(base + "/stop").raise_for_status()
            deadline = time.monotonic() + 90
            while client.get(base + "/stats/requests").json()["state"] != "stopped":
                assert time.monotonic() < deadline, "Traffic did not stop"
                time.sleep(1)
            assert client.get(base).status_code == 200
            stopped = client.get("http://api:8080/api/v1/dashboard").json()["totals"]["transfers"]
            time.sleep(3)
            assert (
                client.get("http://api:8080/api/v1/dashboard").json()["totals"]["transfers"]
                == stopped
            )
