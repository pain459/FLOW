from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeout
import asyncio
import logging
import re
from uuid import uuid4
from apps.pulsepay.domain.errors import BusinessError
from apps.pulsepay.api.v1.accounts import router as accounts_router
from apps.pulsepay.api.v1.transfers import router as transfers_router
from shared.logging import request_id_var
from apps.pulsepay.infrastructure.db import Database
from shared.config import settings
from shared.logging import configure_logging
from apps.pulsepay.infrastructure.redis import Cache
from shared import metrics
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from fastapi import Response
from sqlalchemy import text
import time
from typing import Any
from shared.telemetry import setup_telemetry, shutdown_telemetry
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from apps.pulsepay.infrastructure.limits import RequestSizeLimit
from asyncpg import PostgresConnectionError, InvalidPasswordError
from opentelemetry.trace import Span
from starlette.types import Scope

config = settings()
db = Database(config)
cache = Cache(config)
HTTP_METHOD_LABELS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(config.service_name, config.log_level)
    setup_telemetry(config.service_name, db.engine)
    yield
    await db.close()
    await cache.close()
    shutdown_telemetry()


app = FastAPI(title="PulsePay synthetic transaction laboratory", version="1.0.0", lifespan=lifespan)
app.include_router(accounts_router)
app.include_router(transfers_router)


def capture_request_trace(span: Span, scope: Scope) -> None:
    context = span.get_span_context()
    if context.is_valid:
        scope["pulsepay_trace_id"] = format(context.trace_id, "032x")


FastAPIInstrumentor.instrument_app(
    app, excluded_urls="/health/.*, /metrics", server_request_hook=capture_request_trace
)
app.add_middleware(RequestSizeLimit, max_bytes=16384, timeout=config.request_timeout_seconds)


def error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"code": code, "message": message, "request_id": request_id_var.get()},
        status_code=status,
        headers={"X-Request-ID": request_id_var.get()},
    )


@app.exception_handler(BusinessError)
async def business_error(request: Request, exc: BusinessError):
    return error(exc.code, exc.message, exc.status)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    return error("INVALID_TRANSFER", "Request validation failed", 422)


@app.exception_handler(DBAPIError)
@app.exception_handler(PoolTimeout)
@app.exception_handler(OSError)
@app.exception_handler(PostgresConnectionError)
@app.exception_handler(InvalidPasswordError)
async def database_error(request: Request, exc: Exception):
    metrics.db_errors.labels(
        "constraint" if isinstance(exc, IntegrityError) else "unavailable"
    ).inc()
    logging.getLogger(__name__).error(
        "database_operation_failed", extra={"error_class": type(exc).__name__}
    )
    return error(
        "INTERNAL_ERROR" if isinstance(exc, IntegrityError) else "DATABASE_UNAVAILABLE",
        "Transaction could not be completed"
        if isinstance(exc, IntegrityError)
        else "Database unavailable",
        500 if isinstance(exc, IntegrityError) else 503,
    )


@app.middleware("http")
async def request_boundary(request: Request, call_next):
    started = time.monotonic()
    supplied = request.headers.get("X-Request-ID", "")
    rid = supplied if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", supplied) else str(uuid4())
    token = request_id_var.set(rid)
    try:
        if int(request.headers.get("content-length", "0")) > 16384:
            response = error("INVALID_TRANSFER", "Request exceeds 16 KiB", 413)
        else:
            async with asyncio.timeout(config.request_timeout_seconds):
                response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        method = request.method if request.method in HTTP_METHOD_LABELS else "OTHER"
        metrics.http_requests.labels(method, path, f"{response.status_code // 100}xx").inc()
        metrics.http_duration.labels(method, path).observe(time.monotonic() - started)
        logging.getLogger(__name__).info(
            "http_request",
            extra={"event": "http_request", "trace_id": request.scope.get("pulsepay_trace_id", "")},
        )
        return response
    except TimeoutError:
        return error(
            "DATABASE_UNAVAILABLE", "Request timed out; retry writes with the same key", 503
        )
    except Exception as exc:
        logging.getLogger(__name__).error(
            "request_failed", extra={"error_class": type(exc).__name__}
        )
        return error("INTERNAL_ERROR", "Unexpected request failure", 500)
    finally:
        request_id_var.reset(token)


@app.get("/health/live", tags=["operations"])
async def live():
    return {"status": "HEALTHY", "observed_at": datetime.now(timezone.utc).isoformat()}


@app.get("/health/ready", tags=["operations"])
async def ready():
    try:
        ok = await db.ready()
    except Exception:
        ok = False
    return JSONResponse(
        {
            "status": "HEALTHY" if ok else "UNHEALTHY",
            "reason": "READY" if ok else "DATABASE_OR_SCHEMA_UNAVAILABLE",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        },
        status_code=200 if ok else 503,
    )


@app.get("/metrics", tags=["operations"])
async def prometheus():
    metrics.service_up.labels("api").set(1)
    try:
        metrics.service_up.labels("postgres").set(int(await db.ready()))
    except Exception:
        metrics.service_up.labels("postgres").set(0)
    try:
        metrics.service_up.labels("redis").set(int(bool(await cache.redis.ping())))
    except Exception:
        metrics.service_up.labels("redis").set(0)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health/dependencies", tags=["operations"])
async def dependencies():
    observed = datetime.now(timezone.utc).isoformat()
    try:
        db_ok = await db.ready()
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(await cache.redis.ping())
    except Exception:
        redis_ok = False
    metrics.service_up.labels("postgres").set(int(db_ok))
    metrics.service_up.labels("redis").set(int(redis_ok))
    components: dict[str, dict[str, Any]] = {
        "postgres": {
            "status": "HEALTHY" if db_ok else "UNHEALTHY",
            "observed_at": observed,
            "signal_age_seconds": 0,
            "reason": "READY" if db_ok else "DATABASE_OR_SCHEMA_UNAVAILABLE",
        },
        "redis": {
            "status": "HEALTHY" if redis_ok else "DEGRADED",
            "observed_at": observed,
            "signal_age_seconds": 0,
            "reason": "REACHABLE" if redis_ok else "CACHE_AND_TRANSPORT_UNAVAILABLE",
        },
    }
    for name in ("outbox-relay", "event-worker"):
        components[name] = {
            "status": "UNKNOWN",
            "observed_at": None,
            "signal_age_seconds": None,
            "reason": "NO_FRESH_HEARTBEAT",
        }
    if db_ok:
        async with db.session() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT *,extract(epoch FROM now()-observed_at) AS age FROM service_heartbeats"
                        )
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                components[row["service"]] = {
                    "status": row["status"] if row["age"] < 30 else "UNKNOWN",
                    "observed_at": row["observed_at"].isoformat(),
                    "signal_age_seconds": float(row["age"]),
                    "last_success_at": row["last_success_at"].isoformat()
                    if row["last_success_at"]
                    else None,
                    "last_failure_at": row["last_failure_at"].isoformat()
                    if row["last_failure_at"]
                    else None,
                    "reason": row["reason"] if row["age"] < 30 else "STALE_HEARTBEAT",
                }
    return {
        "status": "UNHEALTHY"
        if not db_ok
        else "HEALTHY"
        if redis_ok and all(c["status"] == "HEALTHY" for c in components.values())
        else "DEGRADED",
        "core_transactions_ready": db_ok,
        "observed_at": observed,
        "dependencies": components,
        "instrumentation": {"status": "UNKNOWN", "reason": "EXPORT_DELIVERY_NOT_CONFIRMED"},
    }
