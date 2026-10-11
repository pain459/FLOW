from uuid import uuid4
import pytest
from sqlalchemy import text


async def pool(lab):
    from apps.pulsepay.application.account_service import seed
    from shared.config import Settings

    report = await seed(lab.db, Settings(seed_account_count=4))
    return report["account_ids"]


def body(ids, amount=100, direction=False):
    return {
        "source_account_id": ids[1 if direction else 0],
        "destination_account_id": ids[0 if direction else 1],
        "amount_minor": amount,
        "currency": "INR",
    }


async def send(lab, payload, key=None):
    return await lab.client.post(
        "/api/v1/transfers",
        json=payload,
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def test_account_and_transfer_atomicity(lab):
    created = await lab.client.post(
        "/api/v1/accounts", json={"external_ref": "new", "currency": "INR"}
    )
    assert created.status_code == 201
    assert created.json()["balance_minor"] == 0
    ids = await pool(lab)
    response = await send(lab, body(ids))
    assert response.status_code == 201, response.text
    tid = response.json()["id"]
    async with lab.admin.connect() as c:
        rows = (
            await c.execute(
                text(
                    "SELECT entry_kind, signed_amount_minor FROM ledger_entries WHERE transfer_id=:id"
                ),
                {"id": tid},
            )
        ).all()
        assert sorted(x[1] for x in rows) == [-100, 100]
        assert (
            await c.scalar(
                text("SELECT count(*) FROM outbox_events WHERE aggregate_id=:id"),
                {"id": tid},
            )
            == 1
        )
        assert await c.scalar(text("SELECT sum(balance_minor) FROM accounts")) == 400000
    balance = await lab.client.get(f"/api/v1/accounts/{ids[0]}/balance")
    assert balance.json()["balance_minor"] == 99900
    assert (await lab.client.get(f"/api/v1/transfers/{tid}")).status_code == 200


async def test_seed_repeat_and_idempotency(lab):
    ids = await pool(lab)
    assert await pool(lab) == ids
    a = await send(lab, body(ids), "same")
    b = await send(lab, body(ids), "same")
    assert (a.status_code, b.status_code) == (201, 200)
    assert a.json()["id"] == b.json()["id"]
    assert (await send(lab, body(ids, 101), "same")).status_code == 409
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 1
        assert (
            await c.scalar(
                text(
                    "SELECT sum(signed_amount_minor) FROM ledger_entries WHERE entry_kind='provisioning'"
                )
            )
            == 400000
        )


async def test_read_only_idempotency_lookup_checks_original_payload(lab):
    from apps.pulsepay.domain.transfers import request_hash
    from apps.pulsepay.schemas.transfers import TransferRequest

    ids = await pool(lab)
    payload = body(ids)
    digest = request_hash(TransferRequest.model_validate(payload))
    headers = {"Idempotency-Key": "lost-response", "X-Request-Hash": digest}
    route = "/api/v1/transfers/by-idempotency-key"
    missing = await lab.client.get(route, headers=headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "TRANSFER_NOT_FOUND"
    committed = await send(lab, payload, "lost-response")
    found = await lab.client.get(route, headers=headers)
    assert found.status_code == 200
    assert found.json()["id"] == committed.json()["id"]
    changed = {**headers, "X-Request-Hash": "0" * 64}
    assert (await lab.client.get(route, headers=changed)).status_code == 409
    assert (
        await lab.client.get(route, headers={"Idempotency-Key": "lost-response"})
    ).status_code == 422
    async with lab.admin.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM transfers")) == 1
        assert (
            await connection.scalar(
                text("SELECT count(*) FROM ledger_entries WHERE transfer_id IS NOT NULL")
            )
            == 2
        )
        assert await connection.scalar(text("SELECT sum(balance_minor) FROM accounts")) == 400000


@pytest.mark.parametrize(
    "kind",
    [
        "funds",
        "currency",
        "same",
        "zero",
        "float",
        "boolean",
        "inactive",
        "missing",
        "overflow",
        "key",
    ],
)
async def test_rejection_leaves_no_writes(lab, kind):
    ids = await pool(lab)
    payload = body(ids)
    if kind == "funds":
        payload["amount_minor"] = 100001
    if kind == "currency":
        payload["currency"] = "USD"
    if kind == "same":
        payload["destination_account_id"] = ids[0]
    if kind == "zero":
        payload["amount_minor"] = 0
    if kind == "float":
        payload["amount_minor"] = 1.1
    if kind == "boolean":
        payload["amount_minor"] = True
    if kind == "missing":
        payload["source_account_id"] = str(uuid4())
    if kind in ("inactive", "overflow"):
        async with lab.admin.begin() as c:
            await c.execute(
                text(
                    "UPDATE accounts SET status='suspended' WHERE id=:id"
                    if kind == "inactive"
                    else "UPDATE accounts SET balance_minor=9223372036854775807 WHERE id=:id"
                ),
                {"id": ids[0] if kind == "inactive" else ids[1]},
            )
    response = (
        await send(lab, payload)
        if kind != "key"
        else await lab.client.post("/api/v1/transfers", json=payload)
    )
    assert response.status_code in (404, 409, 422)
    assert set(response.json()) >= {"code", "message", "request_id"}
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 0
        assert await c.scalar(text("SELECT count(*) FROM outbox_events")) == 0
        assert (
            await c.scalar(
                text("SELECT count(*) FROM ledger_entries WHERE entry_kind <> 'provisioning'")
            )
            == 0
        )


async def test_forced_outbox_failure_rolls_back_everything(lab):
    ids = await pool(lab)
    async with lab.admin.begin() as c:
        await c.execute(
            text(
                "ALTER TABLE outbox_events ADD CONSTRAINT forced_failure CHECK (event_type='never')"
            )
        )
    response = await send(lab, body(ids))
    assert response.status_code == 500
    assert "forced_failure" not in response.text
    async with lab.admin.connect() as c:
        assert await c.scalar(text("SELECT count(*) FROM transfers")) == 0
        assert await c.scalar(text("SELECT min(balance_minor) FROM accounts")) == 100000
        assert await c.scalar(text("SELECT count(*) FROM ledger_entries")) == 4


async def test_ledger_immutable_and_verifier_read_only(lab):
    await pool(lab)
    async with lab.db.session() as s:
        with pytest.raises(Exception):
            await s.execute(text("DELETE FROM ledger_entries"))
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(lab.verifier_url)
    try:
        async with engine.begin() as c:
            with pytest.raises(Exception):
                await c.execute(text("UPDATE accounts SET balance_minor=0"))
    finally:
        await engine.dispose()


async def test_history_cursor_and_missing(lab):
    ids = await pool(lab)
    for _ in range(3):
        assert (await send(lab, body(ids))).status_code == 201
    url = f"/api/v1/accounts/{ids[0]}/transactions"
    a = (await lab.client.get(url + "?limit=2")).json()
    b = (await lab.client.get(url, params={"limit": 2, "cursor": a["next_cursor"]})).json()
    assert len(a["items"]) == len(b["items"]) == 2
    assert {x["id"] for x in a["items"]}.isdisjoint({x["id"] for x in b["items"]})
    assert (await lab.client.get(url + "?cursor=invalid")).status_code == 422
    assert (await lab.client.get(f"/api/v1/accounts/{uuid4()}/balance")).status_code == 404
