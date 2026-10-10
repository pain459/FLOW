"""Compare aligned observed windows; missing samples never imply zero traffic."""


def http_agreement(samples: list[dict]) -> dict:
    measured = [
        sample
        for sample in samples
        if sample.get("phase") == "running"
        and sample.get("prometheus", {}).get("values", {}).get("api_http_counter") is not None
    ]
    if len(measured) < 2:
        return {"status": "UNKNOWN", "reason": "INSUFFICIENT_ALIGNED_SAMPLES"}
    first, last = measured[0], measured[-1]
    client = last.get("load", {}).get("measured", {}).get("http", 0) - first.get("load", {}).get(
        "measured", {}
    ).get("http", 0)
    server = (
        last["prometheus"]["values"]["api_http_counter"]
        - first["prometheus"]["values"]["api_http_counter"]
    )
    seconds = last["epoch"] - first["epoch"]
    tolerance = max(10, client / max(seconds, 1) * 10)
    return {
        "status": "PASS" if server >= 0 and abs(server - client) <= tolerance else "UNKNOWN",
        "generator_http_delta": client,
        "api_http_delta": server,
        "window_seconds": seconds,
        "tolerance_requests": tolerance,
        "reason": "Prometheus scrapes every 5 seconds; allow two scrape windows plus bounded inflight completion.",
    }


def required_evidence_healthy(samples: list[dict], health: str) -> bool:
    measured = [sample for sample in samples if sample.get("phase") == "running"]
    return (
        health == "HEALTHY"
        and len(measured) >= 2
        and all(
            not any(
                gap.startswith("scrape:") or "PROMETHEUS_" in gap
                for gap in sample.get("prometheus", {}).get("gaps", [])
            )
            and all(
                sample.get("prometheus", {}).get("values", {}).get(key) is not None
                for key in (
                    "api_http_counter",
                    "db_checked_out",
                    "outbox_pending",
                    "worker_pending",
                    "verifier_status",
                )
            )
            for sample in measured
        )
    )


def integrity_requires_stop(report: dict) -> bool:
    # Operational lag may be DEGRADED during pressure. Corruption/unknown evidence stops.
    return report.get("status") not in {"PASS", "DEGRADED"} or any(
        check.get("status") in {"FAIL", "UNKNOWN"} for check in report.get("checks", [])
    )
