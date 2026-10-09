from uuid import UUID, uuid5, NAMESPACE_URL
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from apps.pulsepay.domain.errors import BusinessError
from apps.pulsepay.infrastructure.db import Database
from apps.pulsepay.persistence.models import Account, LedgerEntry, SeedRun
from apps.pulsepay.schemas.accounts import AccountCreate
from shared.config import Settings


def seed_account_id(version: str, index: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"pulsepay:{version}:{index}")


async def create_account(db: Database, request: AccountCreate, currency: str) -> Account:
    if request.currency != currency:
        raise BusinessError("INVALID_TRANSFER", "Only the configured lab currency is supported")
    async with db.session() as session:
        try:
            async with session.begin():
                account = Account(external_ref=request.external_ref, currency=request.currency)
                session.add(account)
                await session.flush()
            return account
        except IntegrityError:
            raise BusinessError(
                "ACCOUNT_EXISTS", "External reference already exists", 409
            ) from None


async def get_account(db: Database, account_id: UUID) -> Account:
    async with db.session() as session:
        account = await session.get(Account, account_id)
        if account is None:
            raise BusinessError("ACCOUNT_NOT_FOUND", "Account does not exist", 404)
        return account


async def seed(db: Database, config: Settings) -> dict:
    if not await db.ready():
        raise RuntimeError("Expected migration schema is required")
    ids = [seed_account_id(config.seed_version, i) for i in range(config.seed_account_count)]
    async with db.session() as session, session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "seed:" + config.seed_version},
        )
        run = await session.scalar(select(SeedRun).where(SeedRun.version == config.seed_version))
        if run:
            if (run.account_count, run.balance_per_account, run.currency) != (
                config.seed_account_count,
                config.seed_balance_minor,
                config.pulsepay_currency,
            ):
                raise RuntimeError("Seed version already exists with a different configuration")
        else:
            run = SeedRun(
                version=config.seed_version,
                account_count=config.seed_account_count,
                balance_per_account=config.seed_balance_minor,
                currency=config.pulsepay_currency,
                issued_minor=config.seed_account_count * config.seed_balance_minor,
            )
            session.add(run)
            await session.flush()
            for i, aid in enumerate(ids):
                session.add(
                    Account(
                        id=aid,
                        external_ref=f"seed:{config.seed_version}:{i}",
                        currency=config.pulsepay_currency,
                        balance_minor=config.seed_balance_minor,
                    )
                )
            await session.flush()
            for aid in ids:
                session.add(
                    LedgerEntry(
                        account_id=aid,
                        seed_run_id=run.id,
                        entry_kind="provisioning",
                        signed_amount_minor=config.seed_balance_minor,
                        currency=config.pulsepay_currency,
                    )
                )
    return {
        "seed_version": config.seed_version,
        "account_count": config.seed_account_count,
        "total_issued_minor": run.issued_minor,
        "currency": config.pulsepay_currency,
        "account_ids": [str(aid) for aid in ids],
    }
