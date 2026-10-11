import base64
import json
from datetime import datetime
from uuid import UUID
from sqlalchemy import select, tuple_, literal
from apps.pulsepay.application.account_service import get_account
from apps.pulsepay.domain.errors import BusinessError
from apps.pulsepay.infrastructure.db import Database
from apps.pulsepay.persistence.models import LedgerEntry, Transfer


async def get_transfer(db: Database, transfer_id: UUID) -> Transfer:
    async with db.session() as session:
        item = await session.get(Transfer, transfer_id)
        if item is None:
            raise BusinessError("TRANSFER_NOT_FOUND", "Transfer does not exist", 404)
        return item


async def get_transfer_by_key(db: Database, key: str, digest: str) -> Transfer:
    """Observe a committed result without issuing a transfer or changing balances."""
    async with db.session() as session:
        item = await session.scalar(select(Transfer).where(Transfer.idempotency_key == key))
        if item is None:
            raise BusinessError(
                "TRANSFER_NOT_FOUND", "No committed transfer observed for this key", 404
            )
        if item.request_hash != digest:
            raise BusinessError(
                "IDEMPOTENCY_CONFLICT", "Key already used for a different request", 409
            )
        return item


async def history(db: Database, account_id: UUID, limit: int, cursor: str | None) -> dict:
    await get_account(db, account_id)
    query = select(LedgerEntry).where(LedgerEntry.account_id == account_id)
    if cursor:
        try:
            stamp, uid = json.loads(base64.urlsafe_b64decode(cursor))
            query = query.where(
                tuple_(LedgerEntry.created_at, LedgerEntry.id)
                < tuple_(literal(datetime.fromisoformat(stamp)), literal(UUID(uid)))
            )
        except Exception:
            raise BusinessError("INVALID_TRANSFER", "Invalid history cursor") from None
    async with db.session() as session:
        entries = list(
            await session.scalars(
                query.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).limit(
                    limit + 1
                )
            )
        )
    more = len(entries) > limit
    entries = entries[:limit]
    token = (
        base64.urlsafe_b64encode(
            json.dumps([entries[-1].created_at.isoformat(), str(entries[-1].id)]).encode()
        ).decode()
        if more
        else None
    )
    return {
        "items": [
            {
                "id": str(e.id),
                "transfer_id": str(e.transfer_id) if e.transfer_id else None,
                "entry_kind": e.entry_kind,
                "signed_amount_minor": e.signed_amount_minor,
                "currency": e.currency,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "next_cursor": token,
    }
