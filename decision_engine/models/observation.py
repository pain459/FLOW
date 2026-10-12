from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, field_validator

from chaos.observation_contract import validate_snapshot
from decision_engine.models.contracts import StrictModel


class API(StrictModel):
    rps: float | None = Field(default=None, ge=0)
    error_rate_pct: float | None = Field(default=None, ge=0, le=100)
    p50_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)
    p99_ms: float | None = Field(default=None, ge=0)


class Database(StrictModel):
    reachable: StrictBool | None = None
    connection_usage_pct: float | None = Field(default=None, ge=0, le=100)
    lock_waits: float | None = Field(default=None, ge=0)
    deadlocks: float | None = Field(default=None, ge=0)


class Redis(StrictModel):
    reachable: StrictBool | None = None


class Worker(StrictModel):
    outbox_pending: float | None = Field(default=None, ge=0)
    outbox_oldest_seconds: float | None = Field(default=None, ge=0)
    consumer_lag_messages: float | None = Field(default=None, ge=0)
    pending_messages: float | None = Field(default=None, ge=0)
    oldest_pending_age_seconds: float | None = Field(default=None, ge=0)
    consumer_lag_seconds: float | None = Field(default=None, ge=0)


class Workload(StrictModel):
    rps: float | None = Field(default=None, ge=0)
    active_users: float | None = Field(default=None, ge=0, le=10000)
    configured_users: float | None = Field(default=None, ge=0, le=10000)


class Integrity(StrictModel):
    status: Literal["PASS", "FAIL", "UNKNOWN", "DEGRADED", "STALE"]
    verified_at: datetime | None


class ModelState(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    observed_at: datetime
    window_seconds: int = Field(ge=1, le=3600)
    api: API
    database: Database
    redis: Redis
    worker: Worker
    workload: Workload
    integrity: Integrity
    source_quality: dict[str, Literal["FRESH", "STALE", "UNKNOWN"]]
    missing: list[str]
    provenance: dict[str, dict] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def utc_timestamp(cls, v):
        if v.tzinfo is None:
            raise ValueError("timezone required")
        return v

    @field_validator("source_quality")
    @classmethod
    def controlled_sources(cls, v):
        if set(v) - {
            "api",
            "db-observer",
            "event-worker",
            "outbox-relay",
            "verifier",
            "load",
            "dependencies",
            "integrity",
        }:
            raise ValueError("unregistered source")
        return v

    @field_validator("missing")
    @classmethod
    def controlled_missing(cls, v):
        fields = {
            f"{prefix}.{key}"
            for prefix, model in (
                ("api", API),
                ("database", Database),
                ("redis", Redis),
                ("worker", Worker),
                ("load", Workload),
                ("integrity", Integrity),
            )
            for key in model.model_fields
        }
        if set(v) - fields:
            raise ValueError("unregistered signal")
        return v

    @field_validator("provenance")
    @classmethod
    def controlled_provenance(cls, v):
        allowed = {
            "api",
            "db-observer",
            "event-worker",
            "outbox-relay",
            "verifier",
            "load",
            "dependencies",
            "integrity",
        }
        if set(v) - allowed:
            raise ValueError("unregistered provenance")
        for row in v.values():
            if set(row) != {"observed_at", "age_seconds", "max_age_seconds"}:
                raise ValueError("unregistered provenance fields")
            if row["observed_at"] is not None:
                stamp = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("provenance timezone")
            for key in ("age_seconds", "max_age_seconds"):
                val = row[key]
                if val is not None and (
                    isinstance(val, bool)
                    or not isinstance(val, (int, float))
                    or not 0 <= val <= 1e9
                ):
                    raise ValueError("invalid provenance age")
        return v


def from_snapshot(snapshot: dict) -> ModelState:
    validate_snapshot(snapshot)
    return ModelState(
        observed_at=snapshot["observation_time"],
        window_seconds=snapshot["window_seconds"],
        api=snapshot["api"],
        database=snapshot["database"],
        redis=snapshot["redis"],
        worker=snapshot["worker"],
        workload=snapshot["load"],
        integrity={k: snapshot["integrity"][k] for k in ("status", "verified_at")},
        source_quality={k: row["status"] for k, row in snapshot["freshness"]["sources"].items()},
        missing=snapshot["missing_observations"],
        provenance={
            k: {field: row[field] for field in ("observed_at", "age_seconds", "max_age_seconds")}
            for k, row in snapshot["freshness"]["sources"].items()
        },
    )
