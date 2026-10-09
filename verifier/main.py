"""Independent snapshot SQL; deliberately no application imports."""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from shared.config import Settings
from shared import metrics
from verifier.invariants import balances, ledger, transfers, outbox

CHECKS = balances.CHECKS + ledger.CHECKS + transfers.CHECKS + outbox.CHECKS
STATE_VALUE = {"PASS": 0, "FAIL": 1, "UNKNOWN": 2, "DEGRADED": 3}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def reconcile(database_url: str) -> dict:
    report: dict = {
        "check_run_id": str(uuid4()),
        "started_at": now(),
        "status": "UNKNOWN",
        "checks": [],
    }
    engine = create_async_engine(
        database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=5,
        connect_args={
            "timeout": 3,
            "command_timeout": 5,
            "server_settings": {"statement_timeout": "5000"},
        },
    )
    try:
        async with engine.connect() as c:
            c = await c.execution_options(isolation_level="REPEATABLE READ")
            async with c.begin():
                await c.execute(text("SET TRANSACTION READ ONLY"))
                if await c.scalar(text("SELECT version_num FROM alembic_version")) != "0002":
                    raise ValueError("Schema incompatible")
                report["snapshot"] = {
                    "isolation": await c.scalar(text("SHOW transaction_isolation")),
                    "read_only": await c.scalar(text("SHOW transaction_read_only")) == "on",
                }
                for name, table, sql in CHECKS:
                    inspected = int(await c.scalar(text("SELECT count(*) FROM " + table)) or 0)
                    violations = int(await c.scalar(text(sql)) or 0)
                    report["checks"].append(
                        {
                            "name": name,
                            "status": "FAIL" if violations else "PASS",
                            "inspected_records": inspected,
                            "violations": violations,
                            "details": [],
                        }
                    )
                pending, age = (
                    await c.execute(
                        text(
                            "SELECT count(*),coalesce(extract(epoch FROM now()-min(created_at)),0) FROM outbox_events WHERE published_at IS NULL"
                        )
                    )
                ).one()
                missing = int(
                    await c.scalar(
                        text(
                            "SELECT count(*) FROM outbox_events o LEFT JOIN event_projections p ON p.event_id=o.id WHERE p.event_id IS NULL AND o.created_at<now()-interval '30 seconds'"
                        )
                    )
                    or 0
                )
                quarantine = int(await c.scalar(text("SELECT count(*) FROM event_quarantine")) or 0)
                report["events"] = {
                    "outbox_pending": int(pending),
                    "oldest_pending_seconds": float(age),
                    "overdue_projections": missing,
                    "quarantined_messages": quarantine,
                }
                report["checks"].append(
                    {
                        "name": "event_delivery_lag",
                        "status": "DEGRADED"
                        if float(age) > 30 or missing or quarantine
                        else "PASS",
                        "inspected_records": int(
                            await c.scalar(text("SELECT count(*) FROM outbox_events")) or 0
                        ),
                        "violations": 0,
                        "details": [report["events"]],
                    }
                )
                report["totals"] = {
                    "accounts": int(await c.scalar(text("SELECT count(*) FROM accounts")) or 0),
                    "transfers": int(await c.scalar(text("SELECT count(*) FROM transfers")) or 0),
                    "balance_minor": int(
                        await c.scalar(text("SELECT coalesce(sum(balance_minor),0) FROM accounts"))
                        or 0
                    ),
                    "provisioned_minor": int(
                        await c.scalar(
                            text(
                                "SELECT coalesce(sum(signed_amount_minor),0) FROM ledger_entries WHERE entry_kind='provisioning'"
                            )
                        )
                        or 0
                    ),
                }
        report["status"] = (
            "FAIL"
            if any(c["status"] == "FAIL" for c in report["checks"])
            else "DEGRADED"
            if any(c["status"] == "DEGRADED" for c in report["checks"])
            else "PASS"
        )
    except Exception as exc:
        report["status"] = "UNKNOWN"
        report["reason"] = type(exc).__name__
        report["checks"] = [
            {
                "name": n,
                "status": "UNKNOWN",
                "inspected_records": None,
                "violations": None,
                "details": ["Database or compatible schema unavailable"],
            }
            for n, _, _ in CHECKS
        ]
        report["checks"].append(
            {
                "name": "event_delivery_lag",
                "status": "UNKNOWN",
                "inspected_records": None,
                "violations": None,
                "details": [],
            }
        )
        report.pop("totals", None)
        report.pop("events", None)
    finally:
        await engine.dispose()
    report["finished_at"] = now()
    for check in report["checks"]:
        metrics.verification.labels(check["name"]).set(STATE_VALUE[check["status"]])
    metrics.verification.labels("overall").set(STATE_VALUE[report["status"]])
    return report


def exit_code(report: dict) -> int:
    return STATE_VALUE[report["status"]]


class Verifier:
    def __init__(self, config: Settings):
        self.config = config
        self.health = "UNKNOWN"
        self.report: dict = {"status": "UNKNOWN"}

    async def tick(self) -> int:
        self.report = await reconcile(self.config.database_url)
        self.health = {
            "PASS": "HEALTHY",
            "FAIL": "UNHEALTHY",
            "UNKNOWN": "UNKNOWN",
            "DEGRADED": "DEGRADED",
        }[self.report["status"]]
        logging.getLogger(__name__).info("verification_" + self.report["status"].lower())
        return 1


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = Settings(service_name="verifier")
    if args.once:
        report = await reconcile(config.database_url)
        print(json.dumps(report))
        raise SystemExit(exit_code(report))
    from shared.runtime import run_component

    await run_component(Verifier(config), config, interval=config.verifier_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
