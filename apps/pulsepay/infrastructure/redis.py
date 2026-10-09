import json
import logging
from uuid import UUID
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.engine import make_url
from shared.config import Settings
from shared import metrics
from apps.pulsepay.schemas.accounts import CachedSummary


def redis_client(config: Settings) -> Redis:
    return Redis.from_url(
        config.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=2,
        health_check_interval=10,
        max_connections=16,
    )


class Cache:
    def __init__(self, config: Settings, namespace: str | None = None):
        self.redis = redis_client(config)
        self.ttl = config.cache_ttl_seconds
        self.namespace = namespace or str(make_url(config.database_url).database)
        self.healthy = True
        self.currency = config.pulsepay_currency

    def key(self, account_id: UUID) -> str:
        return f"pulsepay:{self.namespace}:summary:{account_id}"

    async def get(self, account_id: UUID) -> dict | None:
        try:
            raw = await self.redis.get(self.key(account_id))
            self.healthy = True
            metrics.redis_operations.labels("get", "success").inc()
            if raw:
                summary = CachedSummary.model_validate_json(raw)
                if str(summary.account_id) != str(account_id) or summary.currency != self.currency:
                    raise ValueError("Invalid cache identity")
                metrics.cache_hits.inc()
                return summary.model_dump(mode="json")
        except (RedisError, ValueError, TypeError):
            self.failure("get")
        metrics.cache_misses.inc()
        return None

    async def put(self, account_id: UUID, value: dict) -> None:
        try:
            await self.redis.set(self.key(account_id), json.dumps(value), ex=self.ttl)
            self.healthy = True
            metrics.redis_operations.labels("set", "success").inc()
        except RedisError:
            self.failure("set")

    async def invalidate(self, *account_ids: UUID) -> None:
        try:
            await self.redis.delete(*(self.key(aid) for aid in account_ids))
            self.healthy = True
            metrics.redis_operations.labels("delete", "success").inc()
        except RedisError:
            self.failure("delete")

    def failure(self, operation: str) -> None:
        self.healthy = False
        metrics.redis_operations.labels(operation, "failure").inc()
        logging.getLogger(__name__).warning("cache_bypassed", extra={"event": "cache_degraded"})

    async def close(self) -> None:
        await self.redis.aclose()
