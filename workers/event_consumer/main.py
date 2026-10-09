import asyncio
import json
import logging
import socket
from uuid import uuid4
from datetime import datetime, timezone
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import text
from apps.pulsepay.infrastructure.db import Database
from apps.pulsepay.infrastructure.redis import redis_client
from shared.config import Settings
from shared.contracts import BusinessEvent
from shared.logging import request_id_var
from shared import metrics
from opentelemetry import trace, propagate

CONSUMER_NAME = "projection-v1"
tracer = trace.get_tracer(__name__)


class Consumer:
    def __init__(self, db: Database, redis: Redis, config: Settings):
        self.db, self.redis, self.config = db, redis, config
        self.name = socket.gethostname() + "-" + uuid4().hex[:8]
        self.cursor = "0-0"
        self.health = "UNKNOWN"

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.config.stream_name, self.config.consumer_group, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def quarantine(self, stream_id: str, fields: dict, reason: str) -> None:
        async with self.db.session() as session, session.begin():
            await session.execute(
                text("""INSERT INTO event_quarantine(stream_id,original,reason)
                VALUES(:id,CAST(:original AS jsonb),:reason) ON CONFLICT DO NOTHING"""),
                {"id": stream_id, "original": json.dumps(fields), "reason": reason},
            )
        metrics.events.labels("quarantined").inc()
        logging.getLogger(__name__).error(
            "event_quarantined", extra={"event": "event_quarantined", "error_class": reason}
        )
        await self.redis.xack(self.config.stream_name, self.config.consumer_group, stream_id)

    async def process(self, stream_id: str, fields: dict) -> None:
        try:
            envelope = BusinessEvent.model_validate_json(fields["event"])
        except (KeyError, ValueError, TypeError):
            await self.quarantine(stream_id, fields, "INVALID_SCHEMA")
            return
        async with self.db.session() as session:
            authoritative = (
                (
                    await session.execute(
                        text(
                            "SELECT aggregate_id,payload,created_at FROM outbox_events WHERE id=:id"
                        ),
                        {"id": envelope.event_id},
                    )
                )
                .mappings()
                .first()
            )
        if (
            not authoritative
            or authoritative["aggregate_id"] != envelope.transfer_id
            or authoritative["payload"] != envelope.model_dump(mode="json")
        ):
            await self.quarantine(stream_id, fields, "UNKNOWN_OR_MISMATCHED_EVENT")
            return
        token = request_id_var.set(envelope.metadata.get("request_id", ""))
        try:
            parent = propagate.extract(envelope.metadata)
            context = trace.get_current_span(parent).get_span_context()
            with tracer.start_as_current_span(
                "event.project", links=[trace.Link(context)] if context.is_valid else []
            ):
                async with self.db.session() as session, session.begin():
                    receipt = await session.scalar(
                        text("""INSERT INTO consumer_receipts(consumer_name,event_id)
                        VALUES(:name,:id) ON CONFLICT DO NOTHING RETURNING event_id"""),
                        {"name": CONSUMER_NAME, "id": envelope.event_id},
                    )
                    if receipt:
                        await session.execute(
                            text("""INSERT INTO event_projections(event_id,transfer_id,projection_type)
                            VALUES(:id,:transfer,'transfer_notification')"""),
                            {"id": envelope.event_id, "transfer": envelope.transfer_id},
                        )
                metrics.events.labels("processed" if receipt else "duplicate").inc()
                metrics.event_lag.observe(
                    max(
                        0,
                        (datetime.now(timezone.utc) - authoritative["created_at"]).total_seconds(),
                    )
                )
                logging.getLogger(__name__).info(
                    "event_processed" if receipt else "event_duplicate"
                )
            await self.redis.xack(self.config.stream_name, self.config.consumer_group, stream_id)
        finally:
            request_id_var.reset(token)

    async def tick(self) -> int:
        await self.ensure_group()
        claimed = await self.redis.xautoclaim(
            self.config.stream_name,
            self.config.consumer_group,
            self.name,
            self.config.reclaim_idle_ms,
            self.cursor,
            count=25,
        )
        self.cursor = claimed[0]
        messages = list(claimed[1])
        fresh = await self.redis.xreadgroup(
            self.config.consumer_group,
            self.name,
            {self.config.stream_name: ">"},
            count=25,
            block=500,
        )
        for _, batch in fresh:
            messages.extend(batch)
        for mid, fields in messages:
            await self.process(mid, fields)
        info = await self.redis.xpending(self.config.stream_name, self.config.consumer_group)
        metrics.consumer_pending.set(info["pending"])
        pending = await self.redis.xpending_range(
            self.config.stream_name, self.config.consumer_group, "-", "+", 25
        )
        metrics.consumer_oldest.set(
            max((p["time_since_delivered"] / 1000 for p in pending), default=0)
        )
        groups = await self.redis.xinfo_groups(self.config.stream_name)
        group = next(g for g in groups if g["name"] == self.config.consumer_group)
        metrics.consumer_lag.set(group.get("lag") or 0)
        self.health = (
            "DEGRADED"
            if pending and max(p["time_since_delivered"] for p in pending) > 60000
            else "HEALTHY"
        )
        return len(messages)


async def main():
    from shared.runtime import run_component

    config = Settings(service_name="event-worker")
    db, redis = Database(config), redis_client(config)
    try:
        await run_component(Consumer(db, redis, config), config, db)
    finally:
        await redis.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
