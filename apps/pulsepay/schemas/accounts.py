from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AccountCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"external_ref": "demo-account-001", "currency": "INR"}]},
    )
    external_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    external_ref: str
    currency: str
    balance_minor: int
    status: str
    created_at: datetime
    updated_at: datetime


class CachedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: UUID
    balance_minor: int = Field(strict=True, ge=0, le=9223372036854775807)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    status: Literal["active", "suspended", "closed"]
    authoritative: Literal[False]
    source_updated_at: datetime
    cached_at: datetime
    max_staleness_seconds: int = Field(strict=True, ge=1, le=60)


class BalanceResponse(BaseModel):
    account_id: UUID
    balance_minor: int
    currency: str
    authoritative: Literal[True]
    source_updated_at: datetime


class SummaryResponse(CachedSummary):
    cache_hit: bool
    cache_status: Literal["HEALTHY", "DEGRADED"]


class LedgerItem(BaseModel):
    id: UUID
    transfer_id: UUID | None
    entry_kind: Literal["transfer_debit", "transfer_credit", "provisioning"]
    signed_amount_minor: int
    currency: str
    created_at: datetime


class LedgerPage(BaseModel):
    items: list[LedgerItem]
    next_cursor: str | None
