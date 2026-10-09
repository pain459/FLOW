"""Low-rate HTTP client, no application imports or database writes."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from uuid import uuid4, uuid5, NAMESPACE_URL
import httpx
from shared.config import Settings
from shared import metrics


@dataclass
class Operation:
    name: str
    method: str
    path: str
    payload: dict | None
    operation_id: str

    def headers(self) -> dict:
        return {
            "X-Request-ID": self.operation_id,
            **({"Idempotency-Key": self.operation_id} if self.method == "POST" else {}),
        }


def pacing(config: Settings) -> float:
    return config.activity_concurrency / config.activity_target_rps


class Activity:
    def __init__(self, config: Settings, client: httpx.AsyncClient):
        self.config, self.client = config, client
        self.rng = random.Random(config.activity_seed)
        self.accounts = [
            str(uuid5(NAMESPACE_URL, f"pulsepay:{config.seed_version}:{i}"))
            for i in range(config.seed_account_count)
        ]
        self.health = "UNKNOWN"
        self.balances = {aid: config.seed_balance_minor for aid in self.accounts}
        self.next_slot = 0.0
        self.pace_lock = asyncio.Lock()

    async def send(self, op: Operation) -> httpx.Response | None:
        for attempt in range(3):
            async with self.pace_lock:
                delay = max(0, self.next_slot - time.monotonic())
                jitter = 1 if self.config.activity_mode == "steady" else self.rng.uniform(0.9, 1.1)
                self.next_slot = (
                    max(self.next_slot, time.monotonic()) + jitter / self.config.activity_target_rps
                )
            await asyncio.sleep(delay)
            metrics.activity_pending.inc()
            started = time.monotonic()
            try:
                response = await self.client.request(
                    op.method, op.path, json=op.payload, headers=op.headers()
                )
                success = response.is_success
                metrics.activity_requests.labels(op.name, "success" if success else "failure").inc()
                logging.getLogger(__name__).log(
                    logging.INFO if success else logging.WARNING,
                    "activity_request_success" if success else "activity_request_failed",
                    extra={"operation_id": op.operation_id},
                )
                if success or response.status_code < 500:
                    return response
            except httpx.HTTPError as exc:
                metrics.activity_requests.labels(op.name, "failure").inc()
                logging.getLogger(__name__).warning(
                    "activity_request_unavailable",
                    extra={"operation_id": op.operation_id, "error_class": type(exc).__name__},
                )
            finally:
                metrics.activity_pending.dec()
                metrics.activity_duration.labels(op.name).observe(time.monotonic() - started)
            await asyncio.sleep(min(4, 2**attempt) + self.rng.uniform(0, 0.2))
        return None

    async def operation(self) -> bool:
        source, destination = self.rng.sample(self.accounts, 2)
        oid = "activity-" + uuid4().hex
        if self.rng.randrange(100) < self.config.activity_read_percent:
            kind = self.rng.choice(["balance", "transactions", "summary"])
            result = await self.send(
                Operation(kind, "GET", f"/api/v1/accounts/{source}/{kind}", None, oid)
            )
            if result is not None and result.is_success and kind == "balance":
                self.balances[source] = result.json()["balance_minor"]
        else:
            # Client-side hints come from the public seed manifest and authoritative HTTP reads.
            # Reserve locally before yielding; PostgreSQL independently validates actual funds.
            amount = min(
                self.balances[source], self.rng.randint(1, self.config.activity_max_amount_minor)
            )
            if amount <= 0:
                metrics.activity_requests.labels("transfer", "insufficient").inc()
                logging.getLogger(__name__).warning(
                    "activity_insufficient_funds", extra={"operation_id": oid}
                )
                refresh = await self.send(
                    Operation(
                        "balance",
                        "GET",
                        f"/api/v1/accounts/{source}/balance",
                        None,
                        oid + "-refresh",
                    )
                )
                if refresh is not None and refresh.is_success:
                    self.balances[source] = refresh.json()["balance_minor"]
                return False
            self.balances[source] -= amount
            payload = {
                "source_account_id": source,
                "destination_account_id": destination,
                "amount_minor": amount,
                "currency": self.config.pulsepay_currency,
            }
            result = await self.send(
                Operation("transfer", "POST", "/api/v1/transfers", payload, oid)
            )
            if result is not None and result.is_success:
                self.balances[destination] += amount
            elif result is not None and result.status_code < 500:
                self.balances[source] += amount
        return result is not None and result.is_success

    async def tick(self) -> int:
        if not self.config.activity_enabled or self.config.activity_mode == "off":
            self.health = "HEALTHY"
            return 0
        outcomes = await asyncio.gather(
            *(self.operation() for _ in range(self.config.activity_concurrency))
        )
        self.health = "HEALTHY" if all(outcomes) else "DEGRADED"
        return len(outcomes)


async def main():
    from shared.runtime import run_component

    config = Settings(service_name="activity")
    async with httpx.AsyncClient(
        base_url=config.api_url,
        timeout=5,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
    ) as client:
        await run_component(Activity(config, client), config, interval=0.05)


if __name__ == "__main__":
    asyncio.run(main())
