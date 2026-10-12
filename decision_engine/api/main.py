import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from decision_engine.adapters.datasets import catalog
from decision_engine.controller.sessions import Controller
from decision_engine.controller.store import Store
from decision_engine.models.contracts import StrictModel, Budgets
from decision_engine.providers.laya_provider import LayaProvider
from decision_engine.tools.registry import catalog as tool_catalog
from decision_engine.http_limits import RequestLimits
from decision_engine.models.live import Ask, answer_view
from decision_engine.models.calls import CallQuery, Explain
from decision_engine.api.auth import operator, router as auth_router


@asynccontextmanager
async def lifespan(app):
    token = os.environ.get("DECISION_API_TOKEN", "")
    if len(token) != 48 or token == "unprovisioned":
        raise RuntimeError("run intelligence-setup to provision API authorization")
    store = await Store.open(os.environ["DECISION_DATABASE_URL"])
    app.state.controller = Controller(store, LayaProvider(), Path("/reports"))
    # Restart preserves in-flight evidence and abstains instead of repeating diagnostics/model requests.
    async with store.pool.acquire(timeout=3) as c, c.transaction():
        interrupted = await c.fetch(
            "UPDATE decision_intel.investigation_sessions SET state='ESCALATED',last_error='CONTROLLER_RESTART',ended_at=now() WHERE ended_at IS NULL RETURNING id"
        )
        for row in interrupted:
            await c.execute(
                "INSERT INTO decision_intel.session_events(session_id,state,reason) VALUES($1,'ESCALATED','CONTROLLER_RESTART')",
                row["id"],
            )
    for row in interrupted:
        await app.state.controller.finalize(
            row["id"],
            "UNKNOWN",
            {
                "suspected_components": [],
                "conclusion_type": "ESCALATED",
                "reason": "CONTROLLER_RESTART; original raw source hash unavailable",
            },
        )
    yield
    for task in list(app.state.controller.tasks.values()):
        task.cancel()
    await asyncio.gather(*list(app.state.controller.tasks.values()), return_exceptions=True)
    await store.pool.close()


app = FastAPI(title="PulsePay investigation intelligence", version="1.0", lifespan=lifespan)
app.add_middleware(RequestLimits)
app.include_router(auth_router)


@app.exception_handler(RequestValidationError)
async def invalid(request, error):
    return JSONResponse(
        {"code": "INVALID_REQUEST", "message": "Request does not match the allowed schema"},
        status_code=422,
    )


class Start(StrictModel):
    dataset_ref: str = Field(pattern=r"^dataset-[a-f0-9]{16}$")
    mode: str = Field(default="shadow", pattern=r"^(shadow|readonly)$")
    budget: Budgets = Field(default_factory=Budgets)


@app.get("/health/live")
async def live():
    return {"status": "HEALTHY", "execution_mode": "shadow", "readonly_execution_enabled": False}


@app.get("/api/v1/intelligence/health")
async def health():
    c = app.state.controller
    try:
        model = await c.provider.health()
    except Exception as exc:
        model = {"status": "UNKNOWN", "error_class": type(exc).__name__}
    try:
        async with c.store.pool.acquire(timeout=3) as connection:
            db = (
                await connection.fetchval("SELECT version_num FROM decision_intel.schema_version")
                == "di0003"
            )
    except Exception:
        db = False
    return {
        "status": "HEALTHY" if db and model.get("status") == "HEALTHY" else "DEGRADED",
        "model": model,
        "database": "HEALTHY" if db else "UNKNOWN",
        "shadow_go": True,
        "gate_scope": "shadow_and_operator_requested_live_suggestions",
        "manual_live_questions": True,
        "analysis_trigger": "explicit_request_only",
        "analysis_busy": await c.store.analysis_busy() or bool(model.get("busy")),
        "readiness_source": "completed_independent_phase3_audit",
        "readonly_go": False,
        "readonly_reason": "Independent executor safety qualification not granted",
    }


@app.get("/api/v1/intelligence/datasets")
async def datasets():
    return {"datasets": catalog()}


@app.get("/api/v1/intelligence/tools")
async def tools():
    return {"tools": tool_catalog()}


@app.get("/api/v1/intelligence/calls")
async def calls(query: Annotated[CallQuery, Query()]):
    try:
        return await app.state.controller.call_collector.list(query)
    except Exception:
        raise HTTPException(503, "CALL_INVENTORY_UNAVAILABLE") from None


@app.get("/api/v1/intelligence/calls/{uid}")
async def call(uid: UUID):
    try:
        result = await app.state.controller.call_collector.detail(uid)
    except LookupError:
        raise HTTPException(404, "CALL_NOT_OBSERVED") from None
    except Exception:
        raise HTTPException(503, "CALL_EVIDENCE_UNAVAILABLE") from None
    result["analysis"] = await app.state.controller.store.call_analysis(uid)
    if "route" in result.get("call", {}):
        from decision_engine.api.links import grafana_links

        result["links"] = grafana_links(result["call"])
    return result


@app.get("/api/v1/intelligence/calls/{uid}/measurements")
async def measurements(uid: UUID):
    try:
        return await app.state.controller.call_collector.state(uid)
    except LookupError:
        raise HTTPException(404, "CALL_NOT_OBSERVED") from None
    except Exception:
        raise HTTPException(503, "CALL_MEASUREMENTS_UNAVAILABLE") from None


@app.post("/api/v1/intelligence/calls/{uid}/explain", status_code=202)
async def explain(
    uid: UUID,
    body: Explain,
    requester=Depends(operator),
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    ),
):
    try:
        identifier, cached = await app.state.controller.start_call(
            uid, requester, idempotency_key, reanalyse=body.reanalyse
        )
    except LookupError:
        raise HTTPException(404, "CALL_NOT_OBSERVED") from None
    except ValueError:
        raise HTTPException(409, "IDEMPOTENCY_CONFLICT") from None
    except RuntimeError:
        raise HTTPException(429, "ANALYSIS_BUSY") from None
    except Exception:
        raise HTTPException(503, "CALL_EVIDENCE_UNAVAILABLE") from None
    return {"id": identifier, "call_id": uid, "cached": cached, "recommendation_only": True}


@app.post("/api/v1/intelligence/ask", status_code=202)
async def ask(
    body: Ask,
    requester=Depends(operator),
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    ),
):
    """Human-triggered observation collection and one typed Laya suggestion."""
    try:
        uid = await app.state.controller.start_live(body, requester, idempotency_key)
    except ValueError:
        raise HTTPException(409, "IDEMPOTENCY_CONFLICT") from None
    except RuntimeError:
        raise HTTPException(429, "Investigation concurrency limit") from None
    return {"id": uid, "mode": "live_question", "recommendation_only": True}


@app.post("/api/v1/intelligence/investigations", status_code=202)
@app.post("/api/v1/intelligence/replays", status_code=202)
async def start(
    body: Start,
    requester=Depends(operator),
    idempotency_key: str = Header(
        alias="Idempotency-Key", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    ),
):
    if body.mode != "shadow":
        raise HTTPException(423, "READONLY_READINESS_NOT_GRANTED")
    try:
        uid = await app.state.controller.start(
            body.dataset_ref, requester, idempotency_key, body.budget
        )
    except ValueError as exc:
        raise HTTPException(
            409 if str(exc) == "IDEMPOTENCY_CONFLICT" else 422,
            "Invalid dataset or idempotency conflict",
        ) from None
    except RuntimeError:
        raise HTTPException(429, "Investigation concurrency limit") from None
    return {"id": uid, "mode": "shadow"}


@app.get("/api/v1/intelligence/investigations")
async def sessions(
    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000)
):
    return {"items": await app.state.controller.store.list(limit, offset)}


@app.get("/api/v1/intelligence/investigations/{uid}")
async def session(uid: UUID):
    result = await app.state.controller.store.get(uid)
    if not result:
        raise HTTPException(404, "Investigation not found")
    result["artifact_status"] = (
        "COMPLETE"
        if (app.state.controller.reports / str(uid) / "checksums.json").is_file()
        else "PARTIAL"
    )
    return result


@app.get("/api/v1/intelligence/investigations/{uid}/timeline")
async def timeline(uid: UUID):
    row = await session(uid)
    result = await app.state.controller.store.timeline(uid)
    if row["mode"] == "live_question":
        decisions = result["decisions"]
        result["first_response"] = (
            answer_view(decisions[0]["observation"], decisions[0]["raw_answer_redacted"])
            if decisions and decisions[0]["validation_status"] == "VALID"
            else None
        )
    call_id = await app.state.controller.store.session_call(uid)
    result["context"] = {"kind": "call_time" if call_id else row["mode"], "call_id": call_id}
    return result


@app.post("/api/v1/intelligence/investigations/{uid}/cancel")
async def cancel(uid: UUID, requester=Depends(operator)):
    await session(uid)
    return await app.state.controller.cancel(uid)


app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "ui", check_dir=False))


@app.get("/", include_in_schema=False)
async def console():
    return FileResponse(Path(__file__).parent / "ui/index.html")
