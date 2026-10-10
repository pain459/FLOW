from uuid import UUID
from fastapi import APIRouter, Query, Response
from apps.pulsepay.application import dashboard_service as service
from apps.pulsepay.schemas import dashboard as schemas
from apps.pulsepay.schemas.errors import ERROR_RESPONSES

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], responses=ERROR_RESPONSES)


@router.get("", response_model=schemas.DashboardSnapshot)
async def overview(response: Response):
    from apps.pulsepay.main import db, config

    response.headers["Cache-Control"] = "no-store"
    return await service.snapshot(db, config.pulsepay_currency)


@router.get("/signals", response_model=schemas.DashboardSignals)
async def signals(response: Response):
    from apps.pulsepay.main import config

    response.headers["Cache-Control"] = "no-store"
    return await service.signals(config)


@router.get("/accounts", response_model=schemas.AccountPage)
async def accounts(
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, max_length=256),
    search: str = Query("", max_length=128),
):
    from apps.pulsepay.main import db

    return await service.accounts(db, limit, cursor, search)


@router.get("/accounts/{account_id}/ledger", response_model=schemas.DashboardLedgerPage)
async def ledger(
    account_id: UUID,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, max_length=256),
):
    from apps.pulsepay.main import db

    return await service.ledger(db, account_id, limit, cursor)


@router.get("/accounts/{account_id}", response_model=schemas.DashboardAccount)
async def account(account_id: UUID):
    from apps.pulsepay.main import db
    from apps.pulsepay.application.account_service import get_account

    result = await get_account(db, account_id)
    return {
        "id": result.id,
        "external_ref": result.external_ref,
        "currency": result.currency,
        "balance_minor": str(result.balance_minor),
        "status": result.status,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
    }


@router.get("/transfers", response_model=schemas.TransferPage)
async def transfers(
    limit: int = Query(25, ge=1, le=100), cursor: str | None = Query(None, max_length=256)
):
    from apps.pulsepay.main import db

    return await service.transfers(db, limit, cursor)


@router.get("/transfers/{transfer_id}", response_model=schemas.TransferDetail)
async def transfer(transfer_id: UUID):
    from apps.pulsepay.main import db

    return await service.transfer_detail(db, transfer_id)
