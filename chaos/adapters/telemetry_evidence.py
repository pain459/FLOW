"""Bounded observations from existing Loki/Tempo, without fault ground truth."""

import json
import time
from typing import Any

import httpx


def collect(since_epoch):
    result: dict[str, Any] = {
        "observed_epoch": time.time(),
        "source": "Loki and Tempo HTTP APIs",
        "logs": [],
        "traces": [],
        "missing": [],
    }
    with httpx.Client(timeout=3, trust_env=False) as client:
        try:
            response = client.get(
                "http://loki:3100/loki/api/v1/query_range",
                params={
                    "query": '{service=~"api|outbox-relay|event-worker"}',
                    "start": str(int(since_epoch * 1e9)),
                    "end": str(int(time.time() * 1e9)),
                    "limit": 100,
                },
            )
            response.raise_for_status()
            rows = response.json()["data"]["result"]
            for stream in rows:
                for timestamp, text in stream["values"]:
                    try:
                        item = json.loads(text)
                        result["logs"].append(
                            {
                                "timestamp_ns": timestamp,
                                "service": stream["stream"].get("service"),
                                **{
                                    key: item.get(key)
                                    for key in (
                                        "event",
                                        "level",
                                        "request_id",
                                        "trace_id",
                                        "operation_id",
                                    )
                                },
                            }
                        )
                    except ValueError:
                        continue
            if not result["logs"]:
                result["missing"].append("NO_LOG_SAMPLES_IN_WINDOW")
            trace_ids = list(
                dict.fromkeys(row["trace_id"] for row in result["logs"] if row.get("trace_id"))
            )[:3]
            # Logs can arrive before the corresponding batched OTLP export.
            # Retain the original IDs/window and wait only for a fixed budget.
            deadline = time.monotonic() + 8
            while trace_ids and not result["traces"] and time.monotonic() < deadline:
                for identifier in trace_ids:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    response = client.get(
                        "http://tempo:3200/api/traces/" + identifier,
                        timeout=min(3, remaining),
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("batches"):
                            result["traces"].append({"trace_id": identifier, "response": data})
                if not result["traces"]:
                    time.sleep(min(1, max(0, deadline - time.monotonic())))
            if not result["traces"]:
                result["missing"].append("NO_RETRIEVABLE_TRACE_SAMPLES_IN_WINDOW")
        except (httpx.HTTPError, ValueError, KeyError):
            result["missing"].append("LOG_OR_TRACE_QUERY_UNAVAILABLE")
    return result
