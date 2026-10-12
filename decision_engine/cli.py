import argparse
import asyncio
import json
import os
import time
from uuid import uuid4

import httpx


async def main(args):
    async with httpx.AsyncClient(
        base_url="http://incident-controller:8092", timeout=15, trust_env=False
    ) as client:
        if args.command == "health":
            response = await client.get("/api/v1/intelligence/health")
            print(json.dumps(response.json()))
            return
        if args.command == "list":
            print(json.dumps((await client.get("/api/v1/intelligence/datasets")).json()))
            return
        if args.command == "report":
            response = await client.get(f"/api/v1/intelligence/investigations/{args.session}")
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
            return
        if args.command == "readonly":
            raise SystemExit(
                "BLOCKED: Phase 3 grants shadow GO only. Independent read-only executor qualification required."
            )
        if args.command == "ask":
            body = {"error_excerpt": args.error or "", "lookback_seconds": args.lookback}
            if args.request_id:
                body["request_id"] = args.request_id
            if args.trace_id:
                body["trace_id"] = args.trace_id
            response = await client.post(
                "/api/v1/intelligence/ask",
                json=body,
                headers={
                    "Authorization": "Bearer " + os.environ["DECISION_API_TOKEN"],
                    "Idempotency-Key": str(uuid4()),
                },
            )
            response.raise_for_status()
            uid, deadline = response.json()["id"], time.monotonic() + 45
            while time.monotonic() < deadline:
                row = (await client.get(f"/api/v1/intelligence/investigations/{uid}")).json()
                if row["ended_at"]:
                    timeline = (
                        await client.get(f"/api/v1/intelligence/investigations/{uid}/timeline")
                    ).json()
                    print(
                        json.dumps(
                            {
                                "id": uid,
                                "state": row["state"],
                                "first_response": timeline.get("first_response"),
                                "last_error": row["last_error"],
                            },
                            indent=2,
                        )
                    )
                    if not timeline.get("first_response"):
                        raise SystemExit(1)
                    return
                await asyncio.sleep(1)
            raise SystemExit("Question deadline reached; inspect/cancel the recorded session")
        datasets = (await client.get("/api/v1/intelligence/datasets")).json()["datasets"]
        if args.qualified:
            from decision_engine.adapters.datasets import QUALIFIED

            chosen = [d for d in datasets if d["id"] in QUALIFIED]
            if len(chosen) != len(QUALIFIED):
                raise SystemExit("Qualified capture set incomplete")
        else:
            chosen = datasets if args.all else [d for d in datasets if d["id"] == args.dataset]
        if not chosen:
            raise SystemExit(
                "No matching recorded dataset. Import sanitized qualified captures first."
            )
        runs = []
        for dataset in chosen:
            response = await client.post(
                "/api/v1/intelligence/replays",
                json={
                    "dataset_ref": dataset["id"],
                    "mode": "shadow",
                    "budget": {"decisions": args.decisions},
                },
                headers={
                    "Authorization": "Bearer " + os.environ["DECISION_API_TOKEN"],
                    "Idempotency-Key": str(uuid4()),
                },
            )
            response.raise_for_status()
            uid = response.json()["id"]
            deadline = time.monotonic() + 190
            while time.monotonic() < deadline:
                row = (await client.get(f"/api/v1/intelligence/investigations/{uid}")).json()
                if row["ended_at"] and (
                    row.get("artifact_status") == "COMPLETE" or row["state"] == "ERROR"
                ):
                    break
                await asyncio.sleep(1)
            else:
                raise RuntimeError("bounded session did not terminate")
            runs.append(
                {
                    "id": uid,
                    "dataset": dataset["id"],
                    "state": row["state"],
                    "last_error": row["last_error"],
                }
            )
            print(json.dumps(runs[-1]), flush=True)
            if row["state"] in ("ERROR", "TIMED_OUT", "CANCELLED") or (
                row["state"] == "ESCALATED" and row["last_error"] != "POLICY_ESCALATION"
            ):
                raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["health", "list", "replay", "readonly", "report", "ask"])
    p.add_argument("--dataset")
    p.add_argument("--all", action="store_true")
    p.add_argument("--qualified", action="store_true")
    p.add_argument("--decisions", type=int, default=8, choices=range(1, 9))
    p.add_argument("--session")
    p.add_argument("--request-id")
    p.add_argument("--trace-id")
    p.add_argument("--error")
    p.add_argument("--lookback", type=int, default=600, choices=range(30, 901))
    asyncio.run(main(p.parse_args()))
