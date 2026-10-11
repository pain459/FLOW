from datetime import datetime, timedelta, timezone

import pytest

from chaos.adapters import observations


def sample():
    now = datetime.now(timezone.utc)
    return {
        "observed_at": now.isoformat(),
        "window_seconds": 30,
        "health": {
            "dependencies": {"postgres": {"status": "HEALTHY"}, "redis": {"status": "HEALTHY"}}
        },
        "metrics": {
            "values": {
                "api_rps": 20,
                "api_5xx_rate": 0,
                "worker_lag": 47,
                "worker_pending": 3,
                "consumer_oldest_seconds": 9,
                "outbox_pending": 0,
                "outbox_oldest_seconds": 0,
                "db_observed_at": (now - timedelta(seconds=3)).timestamp(),
                "worker_observed_at": (now - timedelta(seconds=3)).timestamp(),
                "relay_observed_at": (now - timedelta(seconds=3)).timestamp(),
            },
            "gaps": [],
            "scrapes": {
                name: {"health": "up", "last_scrape": (now - timedelta(seconds=2)).isoformat()}
                for name in (
                    "api",
                    "db-observer",
                    "event-worker",
                    "outbox-relay",
                    "locust",
                    "verifier",
                )
            },
        },
    }


def test_snapshot_exports_source_freshness_without_privileged_labels():
    raw = sample()
    raw["metrics"]["scrapes"]["chaos-watchdog"] = {
        "scenario": "008-postgres-outage",
        "health": "up",
    }
    result = observations.snapshot(raw, "chaos-readiness")
    assert result["schema_version"] == "1.1"
    assert result["freshness"]["sources"]["api"]["status"] == "FRESH"
    assert result["freshness"]["sources"]["api"]["age_seconds"] == pytest.approx(2)
    assert result["freshness"]["sources"]["api"]["source"] == "Prometheus scrape"
    assert "chaos-watchdog" not in result["freshness"]["sources"]


def test_snapshot_does_not_confuse_consumer_units_with_empty_outbox():
    result = observations.snapshot(sample(), "chaos-readiness")
    assert result["worker"]["outbox_oldest_seconds"] == 0
    assert result["worker"]["consumer_lag_messages"] == 47
    assert result["worker"]["pending_messages"] == 3
    assert result["worker"]["oldest_pending_age_seconds"] == 9
    assert result["worker"]["consumer_lag_seconds"] is None
    assert "worker.consumer_lag_seconds" in result["missing_observations"]


@pytest.mark.parametrize("age,expected", [(35, "STALE"), (-60, "UNKNOWN")])
def test_stale_or_future_scrape_cannot_be_presented_as_current(age, expected):
    raw = sample()
    raw["metrics"]["scrapes"]["event-worker"]["last_scrape"] = (
        datetime.fromisoformat(raw["observed_at"]) - timedelta(seconds=age)
    ).isoformat()
    result = observations.snapshot(raw, "chaos-readiness")
    assert result["freshness"]["sources"]["event-worker"]["status"] == expected
    assert result["worker"]["consumer_lag_messages"] is None
    assert "worker.consumer_lag_messages" in result["missing_observations"]


def test_missing_scrape_and_nonfinite_values_remain_unknown():
    raw = sample()
    raw["metrics"]["scrapes"].pop("api")
    raw["metrics"]["values"]["worker_pending"] = float("nan")
    result = observations.snapshot(raw, "chaos-readiness")
    assert result["freshness"]["sources"]["api"]["status"] == "UNKNOWN"
    assert result["api"]["rps"] is None
    assert result["worker"]["pending_messages"] is None
    assert result["integrity"]["status"] == "UNKNOWN"


def test_expired_independent_verification_is_not_presented_as_fresh_pass():
    raw = sample()
    old = (datetime.fromisoformat(raw["observed_at"]) - timedelta(minutes=4)).isoformat()
    result = observations.snapshot(raw, "chaos-readiness", {"status": "PASS", "finished_at": old})
    assert result["integrity"]["status"] == "UNKNOWN"
    assert result["integrity"]["last_observed_status"] == "PASS"
    assert result["freshness"]["sources"]["integrity"]["status"] == "STALE"


@pytest.mark.parametrize(
    "metric,source,section,field",
    [
        ("worker_observed_at", "event-worker", "worker", "consumer_lag_messages"),
        ("relay_observed_at", "outbox-relay", "worker", "outbox_pending"),
        ("db_observed_at", "db-observer", "database", "lock_waits"),
    ],
)
@pytest.mark.parametrize("age,expected", [(35, "STALE"), (None, "UNKNOWN")])
def test_fresh_scrape_cannot_refresh_stalled_producer(
    metric, source, section, field, age, expected
):
    raw = sample()
    raw["metrics"]["values"]["db_lock_waits"] = 0
    raw["metrics"]["values"][metric] = (
        datetime.fromisoformat(raw["observed_at"]).timestamp() - age if age is not None else None
    )
    result = observations.snapshot(raw, "chaos-readiness")
    assert result["freshness"]["sources"][source]["status"] == expected
    assert result[section][field] is None
