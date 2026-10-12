import asyncio
import json
import logging
import random
from uuid import uuid4
from redis.asyncio import Redis
from sqlalchemy import text
from apps.pulsepay.infrastructure.db import Database
from apps.pulsepay.infrastructure.redis import redis_client
from shared.config import Settings
from shared import metrics
from shared.logging import request_id_var, call_id_var
from opentelemetry import propagate, trace

tracer = trace.get_tracer(__name__)


class Relay:
    def __init__(self, db: Database, redis: Redis, config: Settings):
        self.db, self.redis, self.config = db, redis, config
        self.health = "UNKNOWN"

    async def tick(self) -> int:
        token = uuid4()
        async with self.db.session() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text("""WITH batch AS (
                SELECT id FROM outbox_events WHERE published_at IS NULL
                AND next_attempt_at<=now() AND (lease_until IS NULL OR lease_until<now())
                ORDER BY created_at LIMIT 25 FOR UPDATE SKIP LOCKED)
                UPDATE outbox_events o SET claim_token=:token,lease_until=now()+interval '30 seconds',
                publish_attempts=publish_attempts+1 FROM batch WHERE o.id=batch.id
                RETURNING o.id,o.payload,o.publish_attempts"""),
                        {"token": token},
                    )
                )
                .mappings()
                .all()
            )
        published = 0
        self.health = "HEALTHY"
        for row in rows:
            try:
                with tracer.start_as_current_span(
                    "outbox.publish", context=propagate.extract(row["payload"].get("metadata", {}))
                ) as span:
                    request_token = request_id_var.set(
                        row["payload"].get("metadata", {}).get("request_id", "")
                    )
                    call_token = call_id_var.set(
                        row["payload"].get("metadata", {}).get("call_id", "")
                    )
                    if call_id_var.get():
                        span.set_attribute("pulsepay.call_id", call_id_var.get())
                    try:
                        await self.redis.xadd(
                            self.config.stream_name, {"event": json.dumps(row["payload"])}
                        )
                        logging.getLogger(__name__).info(
                            "outbox_published", extra={"event": "outbox_published"}
                        )
                    finally:
                        call_id_var.reset(call_token)
                        request_id_var.reset(request_token)
                metrics.redis_operations.labels("xadd", "success").inc()
            except Exception as exc:
                self.health = "DEGRADED"
                metrics.redis_operations.labels("xadd", "failure").inc()
                delay = min(30, 2 ** min(row["publish_attempts"], 5)) + random.uniform(0, 0.5)
                async with self.db.session() as session, session.begin():
                    await session.execute(
                        text("""UPDATE outbox_events SET claim_token=NULL,lease_until=NULL,
                        last_error=:error,next_attempt_at=now()+make_interval(secs=>:delay)
                        WHERE id=:id AND claim_token=:token"""),
                        {
                            "id": row["id"],
                            "token": token,
                            "error": type(exc).__name__,
                            "delay": delay,
                        },
                    )
                logging.getLogger(__name__).warning(
                    "outbox_publish_retry",
                    extra={
                        "event": "outbox_publish_retry",
                        "error_class": type(exc).__name__,
                        "call_id": row["payload"].get("metadata", {}).get("call_id", ""),
                    },
                )
                continue
            # Redis confirmation precedes DB marker. Crash here deliberately permits duplicates.
            async with self.db.session() as session, session.begin():
                await session.execute(
                    text("""UPDATE outbox_events SET published_at=now(),claim_token=NULL,
                    lease_until=NULL,last_error=NULL WHERE id=:id AND claim_token=:token"""),
                    {"id": row["id"], "token": token},
                )
            published += 1
        if not rows:
            try:
                await self.redis.ping()
            except Exception:
                self.health = "DEGRADED"
        async with self.db.session() as session:
            pending, age = (
                await session.execute(
                    text(
                        "SELECT count(*),coalesce(extract(epoch FROM now()-min(created_at)),0) FROM outbox_events WHERE published_at IS NULL"
                    )
                )
            ).one()
        metrics.outbox_pending.set(pending)
        metrics.outbox_oldest.set(float(age))
        metrics.service_up.labels("redis").set(int(self.health == "HEALTHY"))
        return published


async def main():
    from shared.runtime import run_component

    config = Settings(service_name="outbox-relay")
    db, redis = Database(config), redis_client(config)
    try:
        await run_component(Relay(db, redis, config), config, db)
    finally:
        await redis.aclose()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
