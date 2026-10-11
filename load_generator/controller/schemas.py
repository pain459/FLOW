"""Strict workload contracts. Closed-loop ceilings are never arrival guarantees."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import hashlib
import json
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator

OPERATIONS = {
    "account_read",
    "balance_read",
    "summary_read",
    "history_read",
    "transfer_write",
    "transfer_status",
    "journey",
    "rejection",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThinkTime(StrictModel):
    min: int = Field(default=100, ge=0, le=10000)
    max: int = Field(default=250, ge=0, le=10000)

    @model_validator(mode="after")
    def ordered(self):
        if self.max < self.min:
            raise ValueError("Think time maximum is below minimum")
        return self


class Accounts(StrictModel):
    selection: Literal["uniform", "hot"] = "uniform"
    minimum_funded_accounts: int = Field(default=200, ge=2, le=500)
    hot_account_count: int = Field(default=5, ge=2, le=100)
    transfer_amount_minor_min: int = Field(default=1, ge=1, le=1000)
    transfer_amount_minor_max: int = Field(default=100, ge=1, le=1000)
    avoid_self_transfer: Literal[True] = True
    enforce_safe_funding: Literal[True] = True

    @model_validator(mode="after")
    def ordered(self):
        if self.transfer_amount_minor_max < self.transfer_amount_minor_min:
            raise ValueError("Amount maximum is below minimum")
        if self.selection == "hot" and self.hot_account_count > self.minimum_funded_accounts:
            raise ValueError("Hot subset exceeds funded account requirement")
        return self


class Retry(StrictModel):
    max_attempts: int = Field(default=2, ge=1, le=3)
    backoff_ms: int = Field(default=250, ge=0, le=5000)
    same_idempotency_key: Literal[True] = True
    deliberate_replay_percent: float = Field(default=2, ge=0, le=25)


class Safety(StrictModel):
    max_duration_seconds: int = Field(default=7200, ge=1, le=14400)
    max_concurrent_users: int = Field(default=150, ge=1, le=150)
    stop_on_integrity_failure: Literal[True] = True
    stop_on_sustained_error_rate_pct: float = Field(default=30, gt=0, le=100)
    stop_on_error_window_seconds: int = Field(default=30, ge=5, le=120)
    integrity_unknown_grace_seconds: int = Field(default=0, ge=0, le=30)


class Reporting(StrictModel):
    save_request_samples: Literal[False] = False
    capture_percentiles: list[Literal[50, 95, 99]] = [50, 95, 99]
    capture_prometheus: Literal[True] = True
    capture_verifier: Literal[True] = True


class Stage(StrictModel):
    seconds: int = Field(ge=1, le=14400)
    users: int = Field(ge=1, le=150)


class Profile(StrictModel):
    schema_version: Literal[1]
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    seed: int = Field(ge=0, le=2**31 - 1)
    mode: Literal["closed_loop"] = "closed_loop"
    users: int = Field(ge=1, le=150)
    workers: int = Field(default=1, ge=1, le=4)
    spawn_rate_users_per_second: float = Field(gt=0, le=50)
    duration_seconds: int = Field(ge=1, le=14400)
    warmup_seconds: int = Field(default=30, ge=0, le=120)
    cooldown_seconds: int = Field(default=60, ge=1, le=180)
    reconciliation_seconds: int = Field(default=30, ge=1, le=120)
    request_timeout_seconds: float = Field(default=5, gt=0, le=15)
    target_operations_per_second: float | None = Field(default=20, gt=0, le=500)
    require_redis: bool = True
    stages: list[Stage] = []
    mix: dict[str, float]
    think_time_ms: ThinkTime = ThinkTime()
    accounts: Accounts = Accounts()
    retry: Retry = Retry()
    safety: Safety = Safety()
    reporting: Reporting = Reporting()

    @model_validator(mode="after")
    def valid(self):
        if not self.mix or set(self.mix) - OPERATIONS:
            raise ValueError("Unsupported or empty operation mix")
        if any(not math.isfinite(w) or w < 0 for w in self.mix.values()) or not math.isclose(
            sum(self.mix.values()), 1, abs_tol=1e-8
        ):
            raise ValueError("Mix weights must be nonnegative and sum to one")
        peak = max([self.users] + [s.users for s in self.stages])
        if (
            peak > self.safety.max_concurrent_users
            or self.duration_seconds > self.safety.max_duration_seconds
        ):
            raise ValueError("Profile exceeds its safety ceilings")
        if self.stages and sum(s.seconds for s in self.stages) != self.duration_seconds:
            raise ValueError("Stage durations must sum to measurement duration")
        return self

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def load_profile(name: str, overrides: dict | None = None) -> Profile:
    import yaml

    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in name):
        raise ValueError("Select a named committed workload profile")
    path = Path(__file__).parents[1] / "profiles" / (name + ".yaml")
    values = yaml.safe_load(path.read_text())
    profile = Profile.model_validate(values)
    if overrides:
        values = profile.model_dump()
        if "users" in overrides and values["stages"]:
            cap = overrides["users"]
            for stage in values["stages"]:
                stage["users"] = min(stage["users"], cap)
            overrides = {**overrides, "users": min(profile.users, cap)}
        if "duration_seconds" in overrides and values["stages"]:
            duration = overrides["duration_seconds"]
            if duration < len(values["stages"]):
                raise ValueError("Duration too short for all stages")
            total = sum(s["seconds"] for s in values["stages"])
            sizes = [max(1, round(s["seconds"] * duration / total)) for s in values["stages"][:-1]]
            sizes.append(duration - sum(sizes))
            for stage, seconds in zip(values["stages"], sizes):
                stage["seconds"] = seconds
        values.update(overrides)
        profile = Profile.model_validate(values)
    return profile


def validate_target(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.netloc != "api:8080"
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Only http://api:8080 is an allowed workload target")
    return "http://api:8080"
