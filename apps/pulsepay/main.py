from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.routing import Match
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeout
import asyncio
import logging
import re
from uuid import uuid4
from apps.pulsepay.domain.errors import BusinessError
from apps.pulsepay.api.v1.accounts import router as accounts_router
from apps.pulsepay.api.v1.transfers import router as transfers_router
from shared.logging import request_id_var, call_id_var
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
from pathlib import Path
from opentelemetry import trace
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apps.pulsepay.api.v1.dashboard import router as dashboard_router

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
    for route in app.routes:
        for method in getattr(route, "methods", ()):
            for status_class in ("2xx", "3xx", "4xx", "5xx"):
                metrics.http_requests.labels(
                    method, getattr(route, "path", "unmatched"), status_class
                )
    yield
    await db.close()
    await cache.close()
    shutdown_telemetry()


app = FastAPI(title="PulsePay synthetic transaction laboratory", version="1.0.0", lifespan=lifespan)
app.include_router(accounts_router)
app.include_router(transfers_router)
app.include_router(dashboard_router)
UI_DIRECTORY = Path(__file__).resolve().parent / "ui"
app.mount("/ui", StaticFiles(directory=UI_DIRECTORY, check_dir=False), name="ui")


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(UI_DIRECTORY / "index.html", headers={"Cache-Control": "no-cache"})


def capture_request_trace(span: Span, scope: Scope) -> None:
    # Instrumentation may wrap or be nested inside HTTP middleware. Both
    # boundaries reuse the generated ASGI attempt ID regardless of their order.
    call_id = scope.get("pulsepay_call_id") or str(uuid4())
    scope["pulsepay_call_id"] = call_id
    span.set_attribute("pulsepay.call_id", call_id)
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
    request.scope["pulsepay_error_code"] = exc.code
    return error(exc.code, exc.message, exc.status)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError):
    request.scope["pulsepay_error_code"] = "INVALID_TRANSFER"
    return error("INVALID_TRANSFER", "Request validation failed", 422)


@app.exception_handler(DBAPIError)
@app.exception_handler(PoolTimeout)
@app.exception_handler(OSError)
@app.exception_handler(PostgresConnectionError)
@app.exception_handler(InvalidPasswordError)
async def database_error(request: Request, exc: Exception):
    request.scope["pulsepay_error_code"] = (
        "INTERNAL_ERROR" if isinstance(exc, IntegrityError) else "DATABASE_UNAVAILABLE"
    )
    request.scope["pulsepay_error_class"] = type(exc).__name__
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
    started_at = datetime.now(timezone.utc).isoformat()
    supplied = request.headers.get("X-Request-ID", "")
    rid = supplied if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", supplied) else str(uuid4())
    token = request_id_var.set(rid)
    call_id = request.scope.get("pulsepay_call_id") or str(uuid4())
    request.scope["pulsepay_call_id"] = call_id
    call_token = call_id_var.set(call_id)
    trace.get_current_span().set_attribute("pulsepay.call_id", call_id)
    status_code = 500
    response = None
    try:
        if int(request.headers.get("content-length", "0")) > 16384:
            request.scope["pulsepay_error_code"] = "INVALID_TRANSFER"
            response = error("INVALID_TRANSFER", "Request exceeds 16 KiB", 413)
        else:
            async with asyncio.timeout(config.request_timeout_seconds):
                response = await call_next(request)
        status_code = response.status_code
        return response
    except TimeoutError:
        status_code = 503
        request.scope["pulsepay_error_code"] = "DATABASE_UNAVAILABLE"
        request.scope["pulsepay_error_class"] = "TimeoutError"
        response = error(
            "DATABASE_UNAVAILABLE", "Request timed out; retry writes with the same key", 503
        )
        return response
    except Exception as exc:
        request.scope["pulsepay_error_code"] = "INTERNAL_ERROR"
        request.scope["pulsepay_error_class"] = type(exc).__name__
        logging.getLogger(__name__).error(
            "request_failed", extra={"error_class": type(exc).__name__}
        )
        response = error("INTERNAL_ERROR", "Unexpected request failure", 500)
        return response
    finally:
        if response is not None:
            response.headers["X-Request-ID"] = rid
            response.headers["X-Call-ID"] = call_id
        route = request.scope.get("route")
        if route is None:
            # Early size/receive failures occur before the router sets scope.route.
            # Resolve a code-owned template without logging the raw request path.
            route = next(
                (
                    candidate
                    for candidate in app.routes
                    if getattr(candidate, "methods", None)
                    and candidate.matches(request.scope)[0] in (Match.FULL, Match.PARTIAL)
                ),
                None,
            )
        path = getattr(route, "path", "unmatched")
        method = request.method if request.method in HTTP_METHOD_LABELS else "OTHER"
        duration = time.monotonic() - started
        client_kind = request.headers.get("X-PulsePay-Client", "unknown")
        logging.getLogger(__name__).info(
            "http_request",
            extra={
                "event": "http_request",
                "record_schema": 1,
                "call_id": call_id,
                "trace_id": request.scope.get("pulsepay_trace_id", ""),
                "method": method,
                "route": path,
                "status_code": status_code,
                "duration_ms": round(duration * 1000, 3),
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error_code": request.scope.get("pulsepay_error_code", ""),
                "error_class": request.scope.get("pulsepay_error_class", ""),
                "client_kind": client_kind if client_kind in ("dashboard", "locust") else "unknown",
            },
        )
        metrics.http_requests.labels(method, path, f"{status_code // 100}xx").inc()
        metrics.http_duration.labels(method, path).observe(duration)
        call_id_var.reset(call_token)
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
