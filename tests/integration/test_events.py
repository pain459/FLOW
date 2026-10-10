import asyncio
import json
from uuid import uuid4
from sqlalchemy import text
from redis.asyncio import Redis
from shared.config import Settings
from apps.pulsepay.infrastructure.db import Database
from tests.integration.test_financial import pool, body, send


async def pipeline(lab):
    from workers.outbox_relay.main import Relay
    from workers.event_consumer.main import Consumer

    config = Settings(
        database_url=lab.worker_url,
        stream_name="test:" + uuid4().hex,
        reclaim_idle_ms=100,
    )
    db = Database(config)
    redis = Redis.from_url(config.redis_url, decode_responses=True)
    return config, db, redis, Relay(db, redis, config), Consumer(db, redis, config)


async def test_duplicate_publish_crash_window_has_one_effect(lab):
    ids = await pool(lab)
    assert (await send(lab, body(ids))).status_code == 201
    config, db, redis, relay, consumer = await pipeline(lab)
    try:
        await relay.tick()
        async with lab.admin.begin() as c:
            # Simulate XADD succeeded but published marker was never committed.
            await c.execute(text("UPDATE outbox_events SET published_at=NULL"))
        await relay.tick()
        await consumer.tick()
        async with lab.admin.connect() as c:
            assert await c.scalar(text("SELECT count(*) FROM event_projections")) == 1
            assert await c.scalar(text("SELECT count(*) FROM consumer_receipts")) == 1
        assert await redis.xlen(config.stream_name) == 2
        assert (await redis.xpending(config.stream_name, config.consumer_group))["pending"] == 0
    finally:
        await redis.delete(config.stream_name)
        await redis.aclose()
        await db.close()


async def test_abandoned_pending_recovered_and_malformed_quarantined(lab):
    ids = await pool(lab)
    await send(lab, body(ids))
    config, db, redis, relay, consumer = await pipeline(lab)
    try:
        await relay.tick()
        await consumer.ensure_group()
        pending = await redis.xreadgroup(
            config.consumer_group, "dead-worker", {config.stream_name: ">"}, count=1
        )
        assert pending
        await asyncio.sleep(0.15)
        await consumer.tick()
        invalid = await redis.xadd(config.stream_name, {"event": '{"schema_version":99}'})
        await consumer.tick()
        async with lab.admin.connect() as c:
            assert await c.scalar(text("SELECT count(*) FROM event_projections")) == 1
            assert (
                await c.scalar(
                    text("SELECT count(*) FROM event_quarantine WHERE stream_id=:id"),
                    {"id": invalid},
                )
                == 1
            )
        assert (await redis.xpending(config.stream_name, config.consumer_group))["pending"] == 0
    finally:
        await redis.delete(config.stream_name)
        await redis.aclose()
        await db.close()


async def test_worker_db_failure_does_not_ack(lab):
    ids = await pool(lab)
    await send(lab, body(ids))
    config, db, redis, relay, consumer = await pipeline(lab)
    try:
        await relay.tick()
        async with lab.admin.begin() as c:
            await c.execute(
                text(
                    "ALTER TABLE event_projections ADD CONSTRAINT forced_fail CHECK(projection_type='never')"
                )
            )
        import pytest

        with pytest.raises(Exception):
            await consumer.tick()
        assert (await redis.xpending(config.stream_name, config.consumer_group))["pending"] == 1
        async with lab.admin.begin() as c:
            assert await c.scalar(text("SELECT count(*) FROM consumer_receipts")) == 0
            await c.execute(text("ALTER TABLE event_projections DROP CONSTRAINT forced_fail"))
        await asyncio.sleep(0.15)
        await consumer.tick()
        assert (await redis.xpending(config.stream_name, config.consumer_group))["pending"] == 0
    finally:
        await redis.delete(config.stream_name)
        await redis.aclose()
        await db.close()


async def test_redis_outage_keeps_transfer_and_pending_then_drains(lab):
    ids = await pool(lab)
    config, db, redis, relay, consumer = await pipeline(lab)
    broken = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.1, socket_timeout=0.1)
    try:
        from workers.outbox_relay.main import Relay

        assert (await send(lab, body(ids))).status_code == 201
        await Relay(db, broken, config).tick()
        async with lab.admin.begin() as c:
            assert (
                await c.scalar(
                    text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
                )
                == 1
            )
            assert await c.scalar(text("SELECT publish_attempts FROM outbox_events")) == 1
            await c.execute(text("UPDATE outbox_events SET next_attempt_at=now()"))
        await relay.tick()
        await consumer.tick()
        async with lab.admin.connect() as c:
            assert (
                await c.scalar(
                    text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
                )
                == 0
            )
            assert await c.scalar(text("SELECT count(*) FROM event_projections")) == 1
    finally:
        await broken.aclose()
        await redis.delete(config.stream_name)
        await redis.aclose()
        await db.close()


async def test_summary_ttl_and_redis_fallback(lab, monkeypatch):
    from apps.pulsepay.infrastructure.redis import Cache
    import apps.pulsepay.main as main

    ids = await pool(lab)
    config = Settings(cache_ttl_seconds=1)
    cache = Cache(config, namespace=uuid4().hex)
    monkeypatch.setattr(main, "cache", cache)
    url = f"/api/v1/accounts/{ids[0]}/summary"
    try:
        first = await lab.client.get(url)
        assert first.status_code == 200
        assert first.json()["cache_hit"] is False
        assert (await lab.client.get(url)).json()["cache_hit"] is True
        await asyncio.sleep(1.05)
        assert (await lab.client.get(url)).json()["cache_hit"] is False
        original = cache.redis
        cache.redis = Redis(
            host="127.0.0.1", port=1, socket_connect_timeout=0.1, socket_timeout=0.1
        )
        result = await lab.client.get(url)
        assert result.status_code == 200
        assert result.json()["cache_status"] == "DEGRADED"
        assert (await send(lab, body(ids))).status_code == 201
        assert (await lab.client.get(f"/api/v1/accounts/{ids[0]}/balance")).json()[
            "balance_minor"
        ] == 99900
        await cache.redis.aclose()
        cache.redis = original
    finally:
        await cache.close()


async def test_valid_schema_forged_event_is_quarantined(lab):
    ids = await pool(lab)
    first = await send(lab, body(ids))
    second = await send(lab, body(ids), "second-event")
    config, db, redis, relay, consumer = await pipeline(lab)
    try:
        async with lab.admin.connect() as c:
            payload = await c.scalar(
                text("SELECT payload FROM outbox_events WHERE aggregate_id=:id"),
                {"id": first.json()["id"]},
            )
        payload["transfer_id"] = second.json()["id"]
        await consumer.ensure_group()
        await redis.xadd(config.stream_name, {"event": json.dumps(payload)})
        await consumer.tick()
        async with lab.admin.connect() as c:
            assert await c.scalar(text("SELECT count(*) FROM event_projections")) == 0
            assert await c.scalar(text("SELECT count(*) FROM consumer_receipts")) == 0
            assert await c.scalar(text("SELECT count(*) FROM event_quarantine")) == 1
    finally:
        await redis.delete(config.stream_name)
        await redis.aclose()
        await db.close()


async def test_malformed_cache_value_falls_back_to_postgres(lab, monkeypatch):
    from apps.pulsepay.infrastructure.redis import Cache
    import apps.pulsepay.main as main

    ids = await pool(lab)
    cache = Cache(Settings(), namespace=uuid4().hex)
    monkeypatch.setattr(main, "cache", cache)
    try:
        await cache.redis.set(cache.key(ids[0]), "[1,2,3]", ex=10)
        response = await lab.client.get(f"/api/v1/accounts/{ids[0]}/summary")
        assert response.status_code == 200
        assert response.json()["balance_minor"] == 100000
        assert response.json()["authoritative"] is False
        assert response.json()["cache_hit"] is False
    finally:
        await cache.close()
