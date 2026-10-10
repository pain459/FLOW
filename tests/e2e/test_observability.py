import asyncio
import base64
import json
import os
import time
from uuid import uuid4
import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("OBSERVABILITY_TEST") != "true",
    reason="Live observability gate: run make observe-test",
)


async def poll(client, url, params, accept, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = (await client.get(url, params=params)).json()
            if accept(data):
                return data
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(1)
    raise AssertionError(f"Timed out waiting for evidence at {url}")


async def test_real_metrics_logs_traces_and_dashboard_queries():
    from uuid import uuid5, NAMESPACE_URL
    from shared.config import Settings

    config = Settings()

    rid = "observability-" + uuid4().hex
    async with httpx.AsyncClient(timeout=10) as client:
        payload = {
            "source_account_id": str(uuid5(NAMESPACE_URL, f"pulsepay:{config.seed_version}:0")),
            "destination_account_id": str(
                uuid5(NAMESPACE_URL, f"pulsepay:{config.seed_version}:1")
            ),
            "amount_minor": 1,
            "currency": config.pulsepay_currency,
        }
        response = await client.post(
            "http://api:8080/api/v1/transfers",
            json=payload,
            headers={"X-Request-ID": rid, "Idempotency-Key": rid},
        )
        assert response.status_code == 201, response.text
        metrics = (await client.get("http://api:8080/metrics")).text
        assert (
            'http_request_duration_seconds_count{method="POST",route="/api/v1/transfers"}'
            in metrics
        )
        await poll(
            client,
            "http://prometheus:9090/api/v1/query",
            {"query": 'http_requests_total{route="/api/v1/transfers"}'},
            lambda d: bool(d["data"]["result"]),
        )
        logs = await poll(
            client,
            "http://loki:3100/loki/api/v1/query_range",
            {"query": '{job="pulsepay"} |= "' + rid + '"', "limit": 10},
            lambda d: {s["stream"].get("service") for s in d["data"]["result"]}
            >= {"api", "outbox-relay", "event-worker"},
        )
        correlated = {
            s["stream"]["service"]: json.loads(s["values"][0][1])["trace_id"]
            for s in logs["data"]["result"]
        }
        request_trace = correlated["api"]
        assert correlated["outbox-relay"] == request_trace

        def spans(data):
            return [
                span
                for batch in data.get("batches", [])
                for scope in batch.get("scopeSpans", [])
                for span in scope.get("spans", [])
            ]

        async def trace_data(trace_id, name):
            return await poll(
                client,
                "http://tempo:3200/api/traces/" + trace_id,
                {},
                lambda d: any(s["name"] == name for s in spans(d)),
            )

        request_spans = spans(await trace_data(request_trace, "outbox.publish"))
        assert any(
            s.get("kind") == "SPAN_KIND_SERVER" and "transfers" in s["name"] for s in request_spans
        )
        assert any(
            a["key"] == "db.system" and a["value"].get("stringValue") == "postgresql"
            for s in request_spans
            for a in s.get("attributes", [])
        )
        assert any(s["name"] == "outbox.publish" for s in request_spans)
        worker_spans = spans(await trace_data(correlated["event-worker"], "event.project"))
        projections = [s for s in worker_spans if s["name"] == "event.project"]
        assert projections
        assert any(
            base64.b64decode(link["traceId"]).hex() == request_trace
            for s in projections
            for link in s.get("links", [])
        )
        from pathlib import Path

        grafana_auth = httpx.BasicAuth("admin", os.environ["GRAFANA_PASSWORD"])
        sources = (
            await client.get("http://grafana:3000/api/datasources", auth=grafana_auth)
        ).json()
        assert {s["uid"] for s in sources} >= {"prometheus", "loki", "tempo"}
        panel_count = 0

        for file in Path("observability/grafana/dashboards").glob("*.json"):
            dashboard = json.loads(file.read_text())
            provisioned = await client.get(
                "http://grafana:3000/api/dashboards/uid/" + dashboard["uid"],
                auth=grafana_auth,
            )
            assert provisioned.status_code == 200
            assert provisioned.json()["meta"]["provisioned"] is True
            if (
                "load" in dashboard.get("tags", [])
                and os.getenv("LOAD_OBSERVABILITY_TEST") != "true"
            ):
                continue  # Opt-in generator metrics are absent during ordinary idle operation.
            for panel in dashboard["panels"]:
                if panel.get("datasource", {}).get("uid") == "prometheus":
                    for target in panel.get("targets", []):
                        result = await poll(
                            client,
                            "http://prometheus:9090/api/v1/query",
                            {"query": target["expr"]},
                            lambda d: d["status"] == "success" and bool(d["data"]["result"]),
                        )
                        assert result["data"]["result"], panel["title"]
                        panel_count += 1
        if os.getenv("OBSERVABILITY_EVIDENCE"):
            Path(os.environ["OBSERVABILITY_EVIDENCE"]).write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "request_id": rid,
                        "request_trace_id": request_trace,
                        "worker_trace_id": correlated["event-worker"],
                        "checked_prometheus_panels": panel_count,
                        "provisioned_datasources": sorted(s["uid"] for s in sources),
                    },
                    indent=2,
                )
            )
