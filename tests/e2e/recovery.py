"""Acceptance probes; Docker lifecycle control stays in the host shell script."""

import argparse
import asyncio
import json
import time
from uuid import uuid5, NAMESPACE_URL
from datetime import datetime, timezone
import httpx
from redis.asyncio import Redis
from shared.config import Settings


async def wait(probe, accept, seconds=75):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = await probe()
            if accept(last):
                return last
        except Exception as exc:
            last = type(exc).__name__
        await asyncio.sleep(1)
    raise AssertionError(f"Recovery evidence not observed: {last}")


async def main(stage, key):
    config = Settings()
    result = {
        "stage": stage,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "UNKNOWN",
    }
    ids = [str(uuid5(NAMESPACE_URL, f"pulsepay:{config.seed_version}:{i}")) for i in (0, 1)]
    body = {
        "source_account_id": ids[0],
        "destination_account_id": ids[1],
        "amount_minor": 11,
        "currency": config.pulsepay_currency,
    }
    async with httpx.AsyncClient(timeout=10) as c:

        async def get(url):
            return (await c.get(url)).json()

        if stage == "redis-outage":
            r = await c.post(
                "http://api:8080/api/v1/transfers",
                json=body,
                headers={"Idempotency-Key": key, "X-Request-ID": key},
            )
            assert r.status_code == 201, r.text
            assert (await c.get("http://api:8080/health/ready")).status_code == 200
            health = await get("http://api:8080/health/dependencies")
            assert health["dependencies"]["redis"]["status"] == "DEGRADED"
            summary = await get("http://api:8080/api/v1/accounts/" + ids[0] + "/summary")
            assert summary["cache_status"] == "DEGRADED"
            report = await wait(
                lambda: get("http://verifier:9100/report"),
                lambda r: r.get("events", {}).get("outbox_pending", 0) > 0,
            )
            assert all(
                ch["status"] == "PASS"
                for ch in report["checks"]
                if ch["name"] != "event_delivery_lag"
            )
            result.update(transfer=r.json(), pending=report["events"]["outbox_pending"])
        elif stage == "redis-recovery":
            report = await wait(
                lambda: get("http://verifier:9100/report"),
                lambda r: r["status"] == "PASS" and r["events"]["outbox_pending"] == 0,
            )
            r = await c.post(
                "http://api:8080/api/v1/transfers",
                json=body,
                headers={"Idempotency-Key": key},
            )
            assert r.status_code == 200, r.text
            result["report"] = report
        elif stage == "pending-setup":
            redis = Redis.from_url("redis://redis:6379/0", decode_responses=True)
            try:
                r = await c.post(
                    "http://api:8080/api/v1/transfers",
                    json=body,
                    headers={"Idempotency-Key": key + "-pending"},
                )
                assert r.status_code == 201, r.text
                await wait(
                    lambda: redis.xreadgroup(
                        "pulsepay-projection-v1",
                        "acceptance-abandoned",
                        {"pulsepay:events:v1": ">"},
                        count=1,
                        block=500,
                    ),
                    bool,
                )
                result["pending"] = (
                    await redis.xpending("pulsepay:events:v1", "pulsepay-projection-v1")
                )["pending"]
                assert result["pending"] >= 1
            finally:
                await redis.aclose()
        elif stage == "pending-recovery":
            redis = Redis.from_url("redis://redis:6379/0", decode_responses=True)
            try:
                await wait(
                    lambda: redis.xpending("pulsepay:events:v1", "pulsepay-projection-v1"),
                    lambda p: p["pending"] == 0,
                )
                result["report"] = await wait(
                    lambda: get("http://verifier:9100/report"),
                    lambda r: r["status"] == "PASS" and r["events"]["outbox_pending"] == 0,
                )
            finally:
                await redis.aclose()
        elif stage == "db-outage":
            assert (await c.get("http://api:8080/health/live")).status_code == 200
            assert (await c.get("http://api:8080/health/ready")).status_code == 503
            balance = await c.get("http://api:8080/api/v1/accounts/" + ids[0] + "/balance")
            assert balance.status_code == 503, balance.text
            result["report"] = await wait(
                lambda: get("http://verifier:9100/report"),
                lambda r: r["status"] == "UNKNOWN",
            )
        elif stage == "db-recovery":
            await wait(
                lambda: c.get("http://api:8080/health/ready"),
                lambda r: r.status_code == 200,
            )
            result["report"] = await wait(
                lambda: get("http://verifier:9100/report"),
                lambda r: r["status"] == "PASS",
            )
        elif stage == "snapshot":
            r = await c.post(
                "http://api:8080/api/v1/transfers",
                json=body,
                headers={
                    "Idempotency-Key": key + "-persist",
                    "X-Request-ID": key + "-persist",
                },
            )
            assert r.status_code == 201, r.text

            async def logs():
                return (
                    await c.get(
                        "http://loki:3100/loki/api/v1/query_range",
                        params={
                            "query": '{job="pulsepay",service="api"} |= "' + key + '-persist"',
                            "limit": 20,
                        },
                    )
                ).json()

            lines = await wait(logs, lambda d: bool(d["data"]["result"]))
            trace_ids = [
                json.loads(v[1]).get("trace_id")
                for stream in lines["data"]["result"]
                for v in stream["values"]
            ]
            result["trace_id"] = next(t for t in trace_ids if t)
            await wait(
                lambda: c.get("http://tempo:3200/api/traces/" + result["trace_id"]),
                lambda r: r.status_code == 200,
            )
            result["query_time"] = time.time() - 10
            prom = (
                await c.get(
                    "http://prometheus:9090/api/v1/query",
                    params={
                        "query": "sum(http_requests_total)",
                        "time": result["query_time"],
                    },
                )
            ).json()
            result["prom_value"] = prom["data"]["result"][0]["value"][1]
            result["transfer_id"] = r.json()["id"]
        elif stage == "persistence":
            from pathlib import Path

            old = json.loads(Path("/evidence/recovery-snapshot.json").read_text())
            await wait(
                lambda: c.get("http://api:8080/health/ready"),
                lambda r: r.status_code == 200,
            )
            assert (
                await c.get("http://api:8080/api/v1/transfers/" + old["transfer_id"])
            ).status_code == 200
            await wait(
                lambda: c.get("http://tempo:3200/api/traces/" + old["trace_id"]),
                lambda r: r.status_code == 200,
            )

            async def prom():
                return (
                    await c.get(
                        "http://prometheus:9090/api/v1/query",
                        params={
                            "query": "sum(http_requests_total)",
                            "time": old["query_time"],
                        },
                    )
                ).json()

            p = await wait(prom, lambda d: bool(d.get("data", {}).get("result")))
            assert p["data"]["result"][0]["value"][1] == old["prom_value"]
            await wait(
                lambda: c.get("http://grafana:3000/api/health"),
                lambda r: r.status_code == 200,
            )

            async def logs():
                return (
                    await c.get(
                        "http://loki:3100/loki/api/v1/query_range",
                        params={"query": '{job="pulsepay",service="api"} |= "' + key + '-persist"'},
                    )
                ).json()

            await wait(logs, lambda d: bool(d["data"]["result"]))
            result.update(
                trace_id=old["trace_id"],
                transfer_id=old["transfer_id"],
                historical_prometheus_preserved=True,
            )
        else:
            raise ValueError("Unknown acceptance stage")
    result["status"] = "PASS"
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage")
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.stage, args.key))
