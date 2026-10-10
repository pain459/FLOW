from datetime import datetime
from typing import Literal, Any
from uuid import UUID
from pydantic import BaseModel, Field

Money = str


class DashboardAccount(BaseModel):
    id: UUID
    external_ref: str
    currency: str
    balance_minor: Money
    status: str
    created_at: datetime
    updated_at: datetime


class DashboardTransfer(BaseModel):
    id: UUID
    source_account_id: UUID
    destination_account_id: UUID
    source_ref: str
    destination_ref: str
    amount_minor: Money
    currency: str
    status: str
    committed_at: datetime
    event_id: UUID | None
    event_status: Literal["PENDING_PUBLICATION", "PENDING_PROCESSING", "PROCESSED"]
    request_id: str | None


class AccountPage(BaseModel):
    items: list[DashboardAccount]
    next_cursor: str | None


class TransferPage(BaseModel):
    items: list[DashboardTransfer]
    next_cursor: str | None


class DashboardLedgerEntry(BaseModel):
    id: UUID
    transfer_id: UUID | None
    entry_kind: str
    signed_amount_minor: Money
    currency: str
    created_at: datetime
    account_id: UUID | None = None
    account_ref: str | None = None


class DashboardLedgerPage(BaseModel):
    items: list[DashboardLedgerEntry]
    next_cursor: str | None


class DashboardTotals(BaseModel):
    accounts: int
    active_accounts: int
    transfers: int
    ledger_entries: int
    balance_minor: Money
    provisioned_minor: Money
    outbox_pending: int
    oldest_pending_seconds: float
    projections: int


class ActivityPoint(BaseModel):
    at: datetime
    count: int


class DashboardSnapshot(BaseModel):
    currency: str
    observed_at: datetime
    totals: DashboardTotals
    activity: list[ActivityPoint]
    recent_transfers: list[DashboardTransfer]


class TransferDetail(BaseModel):
    transfer: DashboardTransfer
    ledger: list[DashboardLedgerEntry]
    traceparent: str | None


class VerificationCheck(BaseModel):
    name: str
    status: Literal["PASS", "FAIL", "UNKNOWN", "DEGRADED"]
    inspected_records: int | None = Field(ge=0)
    violations: int | None = Field(ge=0)
    details: list[Any] = Field(default_factory=list)


class VerificationReport(BaseModel):
    check_run_id: UUID | None = None
    status: Literal["PASS", "FAIL", "UNKNOWN", "DEGRADED"]
    finished_at: datetime
    checks: list[VerificationCheck]


class VerificationSignal(BaseModel):
    status: Literal["PASS", "FAIL", "UNKNOWN", "DEGRADED"] = "UNKNOWN"
    reason: str
    age_seconds: float | None = None
    source_finished_at: datetime | None = None
    report: VerificationReport | None = None


class DashboardSignals(BaseModel):
    observed_at: datetime
    verification: VerificationSignal
