import asyncio
import random
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from opentelemetry import propagate, trace
from apps.pulsepay.domain.errors import BusinessError
from apps.pulsepay.domain.transfers import MAX_MINOR, request_hash
from apps.pulsepay.infrastructure.db import Database
from apps.pulsepay.persistence.models import Account, LedgerEntry, OutboxEvent, Transfer
from apps.pulsepay.schemas.transfers import TransferRequest
from shared.logging import request_id_var, call_id_var

tracer = trace.get_tracer(__name__)


def replay(existing: Transfer, digest: str) -> tuple[Transfer, bool]:
    if existing.request_hash != digest:
        raise BusinessError("IDEMPOTENCY_CONFLICT", "Key already used for a different request", 409)
    return existing, True


async def transfer(db: Database, request: TransferRequest, key: str) -> tuple[Transfer, bool]:
    digest = request_hash(request)
    for attempt in range(3):
        try:
            with tracer.start_as_current_span("transfer.transaction"):
                async with db.session() as session, session.begin():
                    existing = await session.scalar(
                        select(Transfer).where(Transfer.idempotency_key == key)
                    )
                    if existing:
                        return replay(existing, digest)
                    accounts = (
                        await session.scalars(
                            select(Account)
                            .where(
                                Account.id.in_(
                                    [request.source_account_id, request.destination_account_id]
                                )
                            )
                            .order_by(Account.id)
                            .with_for_update()
                        )
                    ).all()
                    # A same-key request may have committed while waiting for account locks.
                    existing = await session.scalar(
                        select(Transfer).where(Transfer.idempotency_key == key)
                    )
                    if existing:
                        return replay(existing, digest)
                    if len(accounts) != 2:
                        raise BusinessError("ACCOUNT_NOT_FOUND", "Account does not exist", 404)
                    by_id = {a.id: a for a in accounts}
                    source, destination = (
                        by_id[request.source_account_id],
                        by_id[request.destination_account_id],
                    )
                    if any(a.status != "active" for a in accounts):
                        raise BusinessError("ACCOUNT_INACTIVE", "Both accounts must be active", 409)
                    if any(a.currency != request.currency for a in accounts):
                        raise BusinessError("INVALID_TRANSFER", "Currencies must match")
                    if source.balance_minor < request.amount_minor:
                        raise BusinessError("INSUFFICIENT_FUNDS", "Insufficient synthetic funds")
                    if destination.balance_minor > MAX_MINOR - request.amount_minor:
                        raise BusinessError(
                            "INVALID_TRANSFER", "Destination balance would overflow"
                        )
                    result = Transfer(
                        id=uuid4(), **request.model_dump(), idempotency_key=key, request_hash=digest
                    )
                    session.add(result)
                    await session.flush()  # Uniqueness races roll back this entire transaction.
                    source.balance_minor -= request.amount_minor
                    destination.balance_minor += request.amount_minor
                    source.updated_at = destination.updated_at = datetime.now(timezone.utc)
                    for account, kind, amount in [
                        (source, "transfer_debit", -request.amount_minor),
                        (destination, "transfer_credit", request.amount_minor),
                    ]:
                        session.add(
                            LedgerEntry(
                                transfer_id=result.id,
                                account_id=account.id,
                                entry_kind=kind,
                                signed_amount_minor=amount,
                                currency=request.currency,
                            )
                        )
                    eid = uuid4()
                    carrier: dict[str, str] = {}
                    propagate.inject(carrier)
                    payload = {
                        "event_id": str(eid),
                        "transfer_id": str(result.id),
                        "schema_version": 1,
                        "event_type": "TransferCommitted",
                        "metadata": {
                            **carrier,
                            "request_id": request_id_var.get(),
                            "call_id": call_id_var.get(),
                        },
                    }
                    session.add(
                        OutboxEvent(
                            id=eid,
                            aggregate_type="transfer",
                            aggregate_id=result.id,
                            event_type="TransferCommitted",
                            schema_version=1,
                            payload=payload,
                        )
                    )
                    await session.flush()
                return result, False  # begin context has committed successfully.
        except IntegrityError as exc:
            # Unique same-key insert on different account pairs: read on a fresh transaction.
            async with db.session() as session:
                existing = await session.scalar(
                    select(Transfer).where(Transfer.idempotency_key == key)
                )
                if existing:
                    return replay(existing, digest)
            raise exc
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate not in ("40P01", "40001") or attempt == 2:
                raise
            await asyncio.sleep(min(0.05 * 2**attempt, 0.2) + random.uniform(0, 0.025))
    raise RuntimeError("Transfer retry exhausted")
