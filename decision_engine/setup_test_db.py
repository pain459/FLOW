"""Disposable decision test database only; never touches the running session DB."""

import asyncio
import os

import asyncpg


async def main():
    c = await asyncpg.connect(
        host="postgres",
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
        command_timeout=5,
    )
    if not await c.fetchval("SELECT 1 FROM pg_database WHERE datname='pulsepay_decision_test'"):
        await c.execute("CREATE DATABASE pulsepay_decision_test OWNER pulsepay_decision_migrator")
    await c.close()
    c = await asyncpg.connect(
        host="postgres",
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database="pulsepay_decision_test",
        command_timeout=5,
    )
    async with c.transaction():
        for name in ("decision_intel", "decision_evaluation"):
            await c.execute(
                f"CREATE SCHEMA IF NOT EXISTS {name} AUTHORIZATION pulsepay_decision_migrator"
            )
        for name in ("accounts", "transfers", "ledger_entries", "outbox_events"):
            await c.execute(
                f"CREATE TABLE IF NOT EXISTS public.{name}(id uuid PRIMARY KEY, balance_minor bigint)"
            )
    await c.close()
    print('{"status":"READY","database":"pulsepay_decision_test","financial_records_created":0}')


if __name__ == "__main__":
    asyncio.run(main())
