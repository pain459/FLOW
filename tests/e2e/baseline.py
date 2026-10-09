"""Timed HTTP-only acceptance observer. Run inside tests container."""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
import httpx
from prometheus_client.parser import text_string_to_metric_families


def counters(raw: str) -> dict:
    result = {}
    for family in text_string_to_metric_families(raw):
        for sample in family.samples:
            if sample.name == "pulsepay_activity_requests_total":
                result[sample.labels["operation"] + ":" + sample.labels["outcome"]] = sample.value
    return result


async def main(seconds: int):
    started = time.monotonic()
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_seconds": seconds,
        "samples": [],
        "status": "UNKNOWN",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        report["initial_counters"] = counters(
            (await client.get("http://activity:9100/metrics")).text
        )
        while True:
            elapsed = time.monotonic() - started
            invariant = (await client.get("http://verifier:9100/report")).json()
            health = (await client.get("http://api:8080/health/dependencies")).json()
            fresh = (
                datetime.now(timezone.utc) - datetime.fromisoformat(invariant["finished_at"])
            ).total_seconds() < 30
            report["samples"].append(
                {
                    "elapsed_seconds": round(elapsed, 3),
                    "invariants": invariant,
                    "core_ready": health["core_transactions_ready"],
                    "fresh": fresh,
                }
            )
            if len(report["samples"]) % 4 == 1:
                print(
                    json.dumps(
                        {
                            "event": "baseline_progress",
                            "elapsed_seconds": round(elapsed),
                            "integrity": invariant["status"],
                            "transfers": invariant.get("totals", {}).get("transfers"),
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
            if elapsed >= seconds:
                break
            await asyncio.sleep(min(15, seconds - elapsed))
        report["final_counters"] = counters((await client.get("http://activity:9100/metrics")).text)
        report["delta_requests"] = {
            k: v - report["initial_counters"].get(k, 0) for k, v in report["final_counters"].items()
        }
        report["elapsed_seconds"] = time.monotonic() - started
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = (
            "PASS"
            if all(
                s["invariants"]["status"] == "PASS" and s["core_ready"] and s["fresh"]
                for s in report["samples"]
            )
            and sum(v for k, v in report["delta_requests"].items() if not k.endswith(":success"))
            == 0
            and report["delta_requests"].get("transfer:success", 0) > 0
            and seconds >= 1800
            else "FAIL"
        )
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=1800)
    asyncio.run(main(parser.parse_args().seconds))
