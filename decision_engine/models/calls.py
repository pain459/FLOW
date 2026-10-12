"""Bounded operator-facing request metadata; never a model input contract."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, field_validator

from decision_engine.models.contracts import StrictModel

ROUTES = frozenset(
    {
        "/api/v1/accounts",
        "/api/v1/accounts/{account_id}",
        "/api/v1/accounts/{account_id}/balance",
        "/api/v1/accounts/{account_id}/summary",
        "/api/v1/accounts/{account_id}/transactions",
        "/api/v1/transfers",
        "/api/v1/transfers/{transfer_id}",
        "/api/v1/transfers/by-idempotency-key",
    }
)


class CallQuery(StrictModel):
    lookback_seconds: int = Field(default=900, ge=30, le=86400)
    limit: int = Field(default=25, ge=1, le=50)
    cursor: str | None = Field(
        default=None,
        max_length=3800,
        pattern=r"^[0-9]{19}(?::[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:,[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}){0,99})?$",
    )
    route: str | None = None
    outcome: Literal[
        "all", "success", "business_rejection", "http_rejection", "infrastructure_error", "slow"
    ] = "all"
    trace_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("route")
    @classmethod
    def registered_route(cls, value):
        if value is not None and value not in ROUTES:
            raise ValueError("unregistered route")
        return value


class Call(StrictModel):
    id: UUID
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    trace_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    started_at: datetime
    completed_at: datetime
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"]
    route: str
    status_code: int = Field(ge=100, le=599)
    duration_ms: float = Field(ge=0, le=900000)
    outcome: Literal["success", "business_rejection", "http_rejection", "infrastructure_error"]
    error_code: str | None = None
    error_class: str | None = None
    client_kind: Literal["dashboard", "locust", "unknown"] = "unknown"

    @field_validator("started_at", "completed_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("timezone required")
        return value


class Explain(StrictModel):
    reanalyse: StrictBool = False
