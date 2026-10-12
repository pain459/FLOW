import logging
import time
from uuid import UUID
from fastapi import APIRouter, Header, Response
from apps.pulsepay.application import transfer_service, queries
from apps.pulsepay.schemas.transfers import TransferRequest, TransferResponse
from apps.pulsepay.schemas.errors import ERROR_RESPONSES
from shared.logging import request_id_var
from shared import metrics

router = APIRouter(prefix="/api/v1/transfers", tags=["transfers"], responses=ERROR_RESPONSES)
log = logging.getLogger(__name__)


@router.post("", status_code=201, response_model=TransferResponse)
async def create(
    request: TransferRequest,
    response: Response,
    idempotency_key: str = Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
):
    from apps.pulsepay.main import db, cache

    started = time.monotonic()
    try:
        result, repeated = await transfer_service.transfer(db, request, idempotency_key)
        metrics.transfers.labels("replayed" if repeated else "committed").inc()
    except Exception:
        metrics.transfers.labels("rejected_or_failed").inc()
        raise
    finally:
        metrics.transfer_duration.observe(time.monotonic() - started)
    await cache.invalidate(request.source_account_id, request.destination_account_id)
    response.status_code = 200 if repeated else 201
    log.info(
        "transfer_replayed" if repeated else "transfer_committed",
        extra={"event": "transfer_replayed" if repeated else "transfer_committed"},
    )
    return TransferResponse.model_validate(result).model_copy(
        update={"request_id": request_id_var.get()}
    )


@router.get("/by-idempotency-key", response_model=TransferResponse)
async def by_key(
    idempotency_key: str = Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
    x_request_hash: str = Header(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
):
    from apps.pulsepay.main import db

    result = await queries.get_transfer_by_key(db, idempotency_key, x_request_hash)
    return TransferResponse.model_validate(result).model_copy(
        update={"request_id": request_id_var.get()}
    )


@router.get("/{transfer_id}", response_model=TransferResponse)
async def get(transfer_id: UUID):
    from apps.pulsepay.main import db

    return TransferResponse.model_validate(await queries.get_transfer(db, transfer_id)).model_copy(
        update={"request_id": request_id_var.get()}
    )
