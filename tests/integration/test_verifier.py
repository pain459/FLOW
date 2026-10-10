import pytest
from sqlalchemy import text
from tests.integration.test_financial import pool, body, send


async def test_independent_verifier_passes_under_concurrent_writes(lab):
    from verifier.main import reconcile
    import asyncio

    ids = await pool(lab)
    writes = asyncio.gather(*(send(lab, body(ids, 1, bool(i % 2))) for i in range(30)))
    reports = await asyncio.gather(*(reconcile(lab.verifier_url) for _ in range(3)))
    assert all(r["status"] == "PASS" for r in reports)
    assert all(r.status_code == 201 for r in await writes)
    assert (await reconcile(lab.verifier_url))["status"] == "PASS"


@pytest.mark.parametrize(
    "corruption", ["imbalance", "missing_outbox", "duplicate_effect", "invalid_account"]
)
async def test_verifier_detects_throwaway_corruption(lab, corruption):
    from verifier.main import reconcile

    ids = await pool(lab)
    await send(lab, body(ids))
    async with lab.admin.begin() as c:
        if corruption == "imbalance":
            await c.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER ledger_immutable"))
            await c.execute(
                text(
                    "UPDATE ledger_entries SET signed_amount_minor=-99 WHERE entry_kind='transfer_debit'"
                )
            )
        elif corruption == "missing_outbox":
            await c.execute(text("DELETE FROM outbox_events"))
        elif corruption == "duplicate_effect":
            await c.execute(
                text("ALTER TABLE event_projections DROP CONSTRAINT event_projections_pkey")
            )
            await c.execute(
                text(
                    "ALTER TABLE event_projections DROP CONSTRAINT event_projections_transfer_id_projection_type_key"
                )
            )
            await c.execute(
                text(
                    "INSERT INTO event_projections SELECT id,aggregate_id,'transfer_notification',now() FROM outbox_events"
                )
            )
            await c.execute(
                text(
                    "INSERT INTO event_projections SELECT id,aggregate_id,'transfer_notification',now() FROM outbox_events"
                )
            )
        else:
            await c.execute(text("ALTER TABLE accounts DROP CONSTRAINT accounts_status_check"))
            await c.execute(
                text("UPDATE accounts SET status='invalid' WHERE id=:id"),
                {"id": ids[0]},
            )
    report = await reconcile(lab.verifier_url)
    assert report["status"] == "FAIL", report
    assert any(c["violations"] > 0 for c in report["checks"])


async def test_verifier_unknown_and_cli_exit(lab):
    from verifier.main import reconcile, exit_code
    from sqlalchemy.engine import make_url

    bad = (
        make_url(lab.verifier_url)
        .set(host="127.0.0.1", port=1)
        .render_as_string(hide_password=False)
    )
    report = await reconcile(bad)
    assert report["status"] == "UNKNOWN"
    assert all(c["status"] == "UNKNOWN" for c in report["checks"])
    assert exit_code(report) == 2
    assert exit_code({"status": "FAIL"}) == 1


async def test_reconciliation_is_read_only_snapshot(lab):
    from verifier.main import reconcile

    await pool(lab)
    report = await reconcile(lab.verifier_url)
    assert report["snapshot"] == {"isolation": "repeatable read", "read_only": True}


async def test_provisioning_redistribution_cannot_hide_behind_totals(lab):
    from verifier.main import reconcile

    ids = await pool(lab)
    async with lab.admin.begin() as c:
        await c.execute(text("ALTER TABLE ledger_entries DISABLE TRIGGER ledger_immutable"))
        for aid, delta in [(ids[0], -100), (ids[1], 100)]:
            await c.execute(
                text(
                    "UPDATE ledger_entries SET signed_amount_minor=signed_amount_minor+:delta WHERE account_id=:id AND entry_kind='provisioning'"
                ),
                {"delta": delta, "id": aid},
            )
            await c.execute(
                text("UPDATE accounts SET balance_minor=balance_minor+:delta WHERE id=:id"),
                {"delta": delta, "id": aid},
            )
    result = await reconcile(lab.verifier_url)
    assert result["status"] == "FAIL"


@pytest.mark.parametrize(
    "mutation",
    [
        "jsonb_set(payload,'{metadata}','null'::jsonb)",
        "payload || jsonb_build_object('unexpected',true)",
        "jsonb_set(payload,'{schema_version}','\"1\"'::jsonb)",
    ],
)
async def test_invalid_durable_event_is_immediate_failure(lab, mutation):
    from verifier.main import reconcile

    ids = await pool(lab)
    await send(lab, body(ids))
    async with lab.admin.begin() as c:
        await c.execute(text("UPDATE outbox_events SET payload=" + mutation))
    assert (await reconcile(lab.verifier_url))["status"] == "FAIL"
