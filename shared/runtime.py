import asyncio
import logging
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Protocol, TYPE_CHECKING
import uvicorn
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

if TYPE_CHECKING:
    from apps.pulsepay.infrastructure.db import Database
from shared.config import Settings
from shared.logging import configure_logging
from shared import metrics


class Component(Protocol):
    health: str

    async def tick(self) -> int: ...


async def write_heartbeat(db: "Database", service: str, state: dict) -> None:
    async with db.session() as session, session.begin():
        await session.execute(
            text("""INSERT INTO service_heartbeats(service,status,observed_at,last_success_at,last_failure_at,reason)
            VALUES(:service,:status,now(),CAST(:success AS timestamptz),CAST(:failure AS timestamptz),:reason)
            ON CONFLICT(service) DO UPDATE SET status=excluded.status,observed_at=excluded.observed_at,
            last_success_at=excluded.last_success_at,last_failure_at=excluded.last_failure_at,reason=excluded.reason"""),
            {
                "service": service,
                "status": state["status"],
                "success": datetime.fromisoformat(state["last_success_at"])
                if state["last_success_at"]
                else None,
                "failure": datetime.fromisoformat(state["last_failure_at"])
                if state["last_failure_at"]
                else None,
                "reason": state["reason"],
            },
        )


async def run_component(
    component: Component,
    config: Settings,
    db: "Database | None" = None,
    interval: float | None = None,
) -> None:
    configure_logging(config.service_name, config.log_level)
    from shared.telemetry import setup_telemetry, shutdown_telemetry

    setup_telemetry(
        config.service_name, db.engine if db is not None else getattr(component, "engine", None)
    )
    state: dict = {
        "status": "UNKNOWN",
        "observed_at": None,
        "last_success_at": None,
        "last_failure_at": None,
    }

    async def loop():
        failures = 0
        while True:
            stamp = datetime.now(timezone.utc).isoformat()
            try:
                await component.tick()
                state.update(status=component.health, observed_at=stamp, reason="PROGRESS_CHECK")
                if component.health == "HEALTHY":
                    state["last_success_at"] = stamp
                else:
                    state["last_failure_at"] = stamp
                failures = 0
            except Exception as exc:
                failures += 1
                state.update(
                    status="UNHEALTHY",
                    observed_at=stamp,
                    last_failure_at=stamp,
                    reason=type(exc).__name__,
                )
                metrics.events.labels("retry").inc()
                logging.getLogger(__name__).error(
                    "component_retry", extra={"error_class": type(exc).__name__}
                )
            metrics.service_up.labels(config.service_name).set(int(state["status"] == "HEALTHY"))
            if db is not None:
                try:
                    await write_heartbeat(db, config.service_name, state)
                except Exception:
                    logging.getLogger(__name__).warning("heartbeat_unavailable")
            await asyncio.sleep(
                (interval or config.worker_poll_seconds)
                if not failures
                else min(30, 2 ** min(failures, 5)) + random.random()
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(loop())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(lifespan=lifespan)

    @app.get("/health/live")
    async def live():
        return {"status": "HEALTHY", "observed_at": datetime.now(timezone.utc).isoformat()}

    @app.get("/health/dependencies")
    async def health():
        return state

    @app.get("/metrics")
    async def prometheus():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/report")
    async def report():
        return getattr(component, "report", state)

    try:
        await uvicorn.Server(
            uvicorn.Config(app, host="0.0.0.0", port=9100, log_config=None, access_log=False)
        ).serve()
    finally:
        shutdown_telemetry()
