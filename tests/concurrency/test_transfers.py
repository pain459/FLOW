import asyncio
from sqlalchemy import text
from tests.integration.test_financial import pool, body, send


async def test_same_key_race(lab):
    ids = await pool(lab)
    results = await asyncio.gather(*(send(lab, body(ids), "race") for _ in range(20)))
    assert sum(r.status_code == 201 for r in results) == 1
    assert all(r.status_code in (200, 201) for r in results)
    assert len({r.json()["id"] for r in results}) == 1
    async with lab.admin.connect() as c:
        assert (
            await c.scalar(
                text("SELECT count(*) FROM ledger_entries WHERE transfer_id IS NOT NULL")
            )
            == 2
        )


async def test_opposing_transfers_conserve_and_reconcile(lab):
    ids = await pool(lab)
    results = await asyncio.wait_for(
        asyncio.gather(*(send(lab, body(ids, 100, bool(i % 2))) for i in range(100))),
        timeout=30,
    )
    assert all(r.status_code == 201 for r in results)
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT sum(balance_minor) FROM accounts")) == 400000
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 100
        assert (
            await c.scalar(
                text(
                    "SELECT count(*) FROM (SELECT transfer_id FROM ledger_entries WHERE transfer_id IS NOT NULL GROUP BY transfer_id HAVING count(*)<>2 OR sum(signed_amount_minor)<>0) q"
                )
            )
            == 0
        )


async def test_same_key_race_across_disjoint_account_locks(lab):
    ids = await pool(lab)
    responses = await asyncio.gather(
        send(lab, body(ids[:2]), "disjoint"), send(lab, body(ids[2:]), "disjoint")
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 1
        assert (
            await c.scalar(
                text("SELECT count(*) FROM ledger_entries WHERE transfer_id IS NOT NULL")
            )
            == 2
        )
        assert (
            await c.scalar(text("SELECT count(*) FROM accounts WHERE balance_minor<>100000")) == 2
        )
        assert await c.scalar(text("SELECT sum(balance_minor) FROM accounts")) == 400000
        assert (
            await c.scalar(
                text(
                    "SELECT count(*) FROM accounts a WHERE balance_minor<>(SELECT sum(signed_amount_minor) FROM ledger_entries l WHERE l.account_id=a.id)"
                )
            )
            == 0
        )
