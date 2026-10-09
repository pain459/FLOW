from uuid import UUID
from fastapi import APIRouter, Query
from apps.pulsepay.application import account_service, queries
from apps.pulsepay.schemas.accounts import (
    AccountCreate,
    AccountResponse,
    BalanceResponse,
    SummaryResponse,
    LedgerPage,
)
from apps.pulsepay.schemas.errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"], responses=ERROR_RESPONSES)


@router.post("", status_code=201, response_model=AccountResponse)
async def create(request: AccountCreate):
    from apps.pulsepay.main import db, config

    return await account_service.create_account(db, request, config.pulsepay_currency)


@router.get("/{account_id}", response_model=AccountResponse)
async def account(account_id: UUID):
    from apps.pulsepay.main import db

    return await account_service.get_account(db, account_id)


@router.get("/{account_id}/balance", response_model=BalanceResponse)
async def balance(account_id: UUID):
    from apps.pulsepay.main import db

    item = await account_service.get_account(db, account_id)
    return {
        "account_id": str(item.id),
        "balance_minor": item.balance_minor,
        "currency": item.currency,
        "authoritative": True,
        "source_updated_at": item.updated_at.isoformat(),
    }


@router.get("/{account_id}/transactions", response_model=LedgerPage)
async def transactions(
    account_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=256),
):
    from apps.pulsepay.main import db

    return await queries.history(db, account_id, limit, cursor)


@router.get("/{account_id}/summary", response_model=SummaryResponse)
async def summary(account_id: UUID):
    from apps.pulsepay.main import db, cache
    from datetime import datetime, timezone

    cached = await cache.get(account_id)
    if cached:
        return {**cached, "cache_hit": True, "cache_status": "HEALTHY"}
    item = await account_service.get_account(db, account_id)
    value = {
        "account_id": str(item.id),
        "balance_minor": item.balance_minor,
        "currency": item.currency,
        "status": item.status,
        "authoritative": False,
        "source_updated_at": item.updated_at.isoformat(),
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "max_staleness_seconds": cache.ttl,
    }
    await cache.put(account_id, value)
    return {**value, "cache_hit": False, "cache_status": "HEALTHY" if cache.healthy else "DEGRADED"}
