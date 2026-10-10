"""Bounded read models; independent reports are observed, never recomputed here."""

import asyncio
import base64
import json
from datetime import datetime, timezone
from uuid import UUID
import httpx
from sqlalchemy import select, text, case, exists, tuple_, literal
from sqlalchemy.orm import aliased
from apps.pulsepay.infrastructure.db import Database
from apps.pulsepay.persistence.models import Account, Transfer, OutboxEvent
from apps.pulsepay.application import queries
from apps.pulsepay.domain.errors import BusinessError
from apps.pulsepay.schemas.dashboard import VerificationReport, ActivitySignal
from shared.config import Settings


def cursor_token(stamp: datetime, uid: UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps([stamp.isoformat(), str(uid)]).encode()).decode()


def cursor_values(cursor: str) -> tuple[datetime, UUID]:
    try:
        stamp, uid = json.loads(base64.urlsafe_b64decode(cursor))
        if not isinstance(stamp, str) or not isinstance(uid, str):
            raise ValueError("Invalid cursor types")
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            raise ValueError("Missing timezone")
        return parsed, UUID(uid)
    except (ValueError, TypeError) as exc:
        raise BusinessError("INVALID_TRANSFER", "Invalid dashboard cursor") from exc


async def accounts(db: Database, limit: int, cursor: str | None, search: str) -> dict:
    query = select(Account)
    if search:
        query = query.where(Account.external_ref.icontains(search, autoescape=True))
    if cursor:
        stamp, uid = cursor_values(cursor)
        query = query.where(
            tuple_(Account.created_at, Account.id) < tuple_(literal(stamp), literal(uid))
        )
    async with db.session() as session:
        rows = list(
            await session.scalars(
                query.order_by(Account.created_at.desc(), Account.id.desc()).limit(limit + 1)
            )
        )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [
            {
                "id": a.id,
                "external_ref": a.external_ref,
                "balance_minor": str(a.balance_minor),
                "currency": a.currency,
                "status": a.status,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            }
            for a in rows
        ],
        "next_cursor": cursor_token(rows[-1].created_at, rows[-1].id) if more else None,
    }


def transfer_query():
    source, destination = aliased(Account), aliased(Account)
    projected = exists(
        select(literal(1))
        .select_from(text("event_projections"))
        .where(text("event_projections.event_id=outbox_events.id"))
    )
    return (
        select(
            Transfer.id,
            Transfer.source_account_id,
            Transfer.destination_account_id,
            source.external_ref.label("source_ref"),
            destination.external_ref.label("destination_ref"),
            Transfer.amount_minor,
            Transfer.currency,
            Transfer.status,
            Transfer.committed_at,
            OutboxEvent.id.label("event_id"),
            case(
                (projected, "PROCESSED"),
                (OutboxEvent.published_at.is_not(None), "PENDING_PROCESSING"),
                else_="PENDING_PUBLICATION",
            ).label("event_status"),
            OutboxEvent.payload["metadata"]["request_id"].astext.label("request_id"),
        )
        .join(source, source.id == Transfer.source_account_id)
        .join(destination, destination.id == Transfer.destination_account_id)
        .outerjoin(OutboxEvent, OutboxEvent.aggregate_id == Transfer.id)
    )


def transfer_row(row) -> dict:
    data = dict(row)
    data["amount_minor"] = str(data["amount_minor"])
    return data


async def transfers(db: Database, limit: int, cursor: str | None) -> dict:
    query = transfer_query()
    if cursor:
        stamp, uid = cursor_values(cursor)
        query = query.where(
            tuple_(Transfer.committed_at, Transfer.id) < tuple_(literal(stamp), literal(uid))
        )
    async with db.session() as session:
        rows = (
            (
                await session.execute(
                    query.order_by(Transfer.committed_at.desc(), Transfer.id.desc()).limit(
                        limit + 1
                    )
                )
            )
            .mappings()
            .all()
        )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [transfer_row(row) for row in rows],
        "next_cursor": cursor_token(rows[-1]["committed_at"], rows[-1]["id"]) if more else None,
    }


async def ledger(db: Database, account_id: UUID, limit: int, cursor: str | None) -> dict:
    page = await queries.history(db, account_id, limit, cursor)
    for entry in page["items"]:
        entry["signed_amount_minor"] = str(entry["signed_amount_minor"])
    return page


async def transfer_detail(db: Database, transfer_id: UUID) -> dict:
    async with db.session() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        row = (
            (await session.execute(transfer_query().where(Transfer.id == transfer_id)))
            .mappings()
            .first()
        )
        if row is None:
            raise BusinessError("TRANSFER_NOT_FOUND", "Transfer does not exist", 404)
        entries = (
            (
                await session.execute(
                    text(
                        "SELECT l.id,l.transfer_id,l.account_id,a.external_ref AS account_ref,l.entry_kind,l.signed_amount_minor,l.currency,l.created_at FROM ledger_entries l JOIN accounts a ON a.id=l.account_id WHERE l.transfer_id=:id ORDER BY l.signed_amount_minor"
                    ),
                    {"id": transfer_id},
                )
            )
            .mappings()
            .all()
        )
        parent = await session.scalar(
            text(
                "SELECT payload->'metadata'->>'traceparent' FROM outbox_events WHERE aggregate_id=:id"
            ),
            {"id": transfer_id},
        )
    return {
        "transfer": transfer_row(row),
        "ledger": [
            {**dict(e), "signed_amount_minor": str(e["signed_amount_minor"])} for e in entries
        ],
        "traceparent": parent,
    }


async def snapshot(db: Database, currency: str) -> dict:
    async with db.session() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        totals = dict(
            (
                await session.execute(
                    text("""SELECT
        (SELECT count(*) FROM accounts) AS accounts,
        (SELECT count(*) FROM accounts WHERE status='active') AS active_accounts,
        (SELECT count(*) FROM transfers) AS transfers,
        (SELECT count(*) FROM ledger_entries) AS ledger_entries,
        (SELECT coalesce(sum(balance_minor),0)::text FROM accounts) AS balance_minor,
        (SELECT coalesce(sum(signed_amount_minor),0)::text FROM ledger_entries WHERE entry_kind='provisioning') AS provisioned_minor,
        (SELECT count(*) FROM outbox_events WHERE published_at IS NULL) AS outbox_pending,
        (SELECT coalesce(extract(epoch FROM now()-min(created_at)),0) FROM outbox_events WHERE published_at IS NULL) AS oldest_pending_seconds,
        (SELECT count(*) FROM event_projections) AS projections""")
                )
            )
            .mappings()
            .one()
        )
        activity = (
            (
                await session.execute(
                    text("""WITH bins AS (SELECT generate_series(date_trunc('minute',now())-interval '29 minutes',date_trunc('minute',now()),interval '1 minute') AS at),
        commits AS (SELECT date_trunc('minute',committed_at) AS at,count(*) AS count FROM transfers WHERE committed_at>=date_trunc('minute',now())-interval '29 minutes' GROUP BY 1)
        SELECT bins.at,coalesce(commits.count,0) AS count FROM bins LEFT JOIN commits USING(at) ORDER BY bins.at""")
                )
            )
            .mappings()
            .all()
        )
        recent = (
            (
                await session.execute(
                    transfer_query()
                    .order_by(Transfer.committed_at.desc(), Transfer.id.desc())
                    .limit(12)
                )
            )
            .mappings()
            .all()
        )
        stamp = await session.scalar(text("SELECT transaction_timestamp()"))
    return {
        "currency": currency,
        "observed_at": stamp,
        "totals": totals,
        "activity": [dict(p) for p in activity],
        "recent_transfers": [transfer_row(r) for r in recent],
    }


async def fetch_json(url: str) -> dict:
    async with (
        asyncio.timeout(2),
        httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=False) as client,
    ):
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("Signal exceeds bound")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("Invalid signal object")
    return value


def signal_age(value: str, now: datetime) -> tuple[datetime, float]:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Missing signal timezone")
    age = (now - stamp).total_seconds()
    if age < -5:
        raise ValueError("Signal clock skew")
    return stamp, max(0, age)


async def verification(config: Settings) -> dict:
    try:
        data = await fetch_json(config.verifier_report_url)
        stamp, age = signal_age(data["finished_at"], datetime.now(timezone.utc))
        if age > 30:
            return {
                "status": "UNKNOWN",
                "reason": "STALE_REPORT",
                "source_finished_at": stamp,
                "age_seconds": age,
                "report": None,
            }
        report = VerificationReport.model_validate(data)
        if report.status != "UNKNOWN" and not report.checks:
            raise ValueError("No check evidence")
        for check in report.checks:
            if check.status != "UNKNOWN" and (
                check.inspected_records is None or check.violations is None
            ):
                raise ValueError("Missing check evidence")
            if check.status == "PASS" and check.violations != 0:
                raise ValueError("Contradictory check evidence")
        states = {check.status for check in report.checks}
        if report.status == "PASS" and states != {"PASS"}:
            raise ValueError("Contradictory report evidence")
        if report.status == "DEGRADED" and (
            "DEGRADED" not in states or states & {"FAIL", "UNKNOWN"}
        ):
            raise ValueError("Contradictory report evidence")
        if report.status == "FAIL" and "FAIL" not in states:
            raise ValueError("Contradictory report evidence")
        return {
            "status": report.status,
            "reason": "INDEPENDENT_SNAPSHOT",
            "age_seconds": age,
            "source_finished_at": stamp,
            "report": report.model_dump(mode="json"),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError):
        return {"status": "UNKNOWN", "reason": "SOURCE_UNAVAILABLE_OR_INVALID", "report": None}


async def activity_signal(config: Settings) -> dict:
    try:
        data = await fetch_json(config.activity_status_url)
        stamp, age = signal_age(data["observed_at"], datetime.now(timezone.utc))
        status = data["status"]
        if status not in {"HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"}:
            raise ValueError("Invalid activity state")
        return ActivitySignal.model_validate(
            {
                "status": status if age <= 30 else "UNKNOWN",
                "reason": data.get("reason", "PROGRESS_CHECK") if age <= 30 else "STALE_SIGNAL",
                "observed_at": stamp,
                "age_seconds": age,
                "last_success_at": data.get("last_success_at"),
                "last_failure_at": data.get("last_failure_at"),
            }
        ).model_dump(mode="json")
    except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError):
        return {"status": "UNKNOWN", "reason": "SOURCE_UNAVAILABLE_OR_INVALID"}


async def signals(config: Settings) -> dict:
    report, activity = await asyncio.gather(verification(config), activity_signal(config))
    return {"observed_at": datetime.now(timezone.utc), "verification": report, "activity": activity}
