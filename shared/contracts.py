from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class BusinessEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    transfer_id: UUID
    schema_version: Literal[1]
    event_type: Literal["TransferCommitted"]
    metadata: dict[str, str] = Field(default_factory=dict)


class ObservationSnapshot(BaseModel):
    schema_version: Literal[1] = 1
    observed_at: datetime
    window_seconds: int = Field(gt=0)
    system: Literal["pulsepay"] = "pulsepay"
    health: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]
    signals: dict
    freshness: dict
    missing_signals: list[str]
