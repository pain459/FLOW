import time
from datetime import datetime
from chaos import state
from chaos.adapters import observations, verification


def healthy(sample):
    health = sample.get("health") or {}
    totals = sample.get("totals") or {}
    values = sample["metrics"]["values"]
    return bool(
        health.get("core_transactions_ready")
        and health.get("status") == "HEALTHY"
        and totals
        and int(totals["transfers"]) - int(totals["projections"]) <= 25
        and totals["oldest_pending_seconds"] < 5
        and not any(
            gap.startswith("scrape:") or "PROMETHEUS" in gap for gap in sample["metrics"]["gaps"]
        )
        and values.get("db_observed_at")
        and time.time() - values["db_observed_at"] < 15
    )


def steady(configuration=None):
    sample = observations.capture()
    result = verification.collect()
    state.event(
        "framework_steady_state_probe",
        healthy=healthy(sample),
        integrity=result["status"],
    )
    return healthy(sample) and result["status"] == "PASS"


def recovery(configuration=None):
    deadline = time.monotonic() + 60
    successes = 0
    lease = state.active()
    load_id = (
        state.read(state.EVIDENCE / lease["run_id"] / "preflight.json", {})
        .get("load", {})
        .get("run_id")
    )
    restored = state.read(state.CONTROL / lease["run_id"] / "restoration.json", {})
    since_epoch = (
        datetime.fromisoformat(restored["finished_at"]).timestamp()
        if restored.get("finished_at")
        else time.time()
    )
    while time.monotonic() < deadline:
        sample = observations.capture()
        from chaos.adapters.evidence import sustained_load

        if healthy(sample) and sustained_load(load_id, since_epoch):
            successes += 1
            if successes >= 3:
                result = verification.collect()
                if result["status"] == "PASS":
                    state.write(
                        state.EVIDENCE / lease["run_id"] / "recovery-verification.json",
                        {
                            "status": "PASS",
                            "verified_at": state.now(),
                            "productive_since_epoch": since_epoch,
                            "sample": sample,
                            "integrity": result,
                        },
                    )
                    state.event("verified_recovery")
                    return True
        else:
            successes = 0
        time.sleep(2)
    state.write(
        state.EVIDENCE / lease["run_id"] / "recovery-verification.json",
        {"status": "FAIL", "verified_at": state.now(), "sample": sample},
    )
    return False
