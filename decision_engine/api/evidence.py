"""Private fixed-read gateway. Only an operator request starts a collection."""

import asyncio
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from decision_engine.models.live import Lookup
from decision_engine.adapters.live_evidence import collect
from decision_engine.http_limits import RequestLimits
from uuid import UUID
from decision_engine.models.calls import CallQuery
from decision_engine.adapters.calls import list_calls, call_detail, call_state, EvidenceUnavailable

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(RequestLimits, timeout_seconds=12)
active = asyncio.Lock()


@app.exception_handler(RequestValidationError)
async def invalid(request, error):
    return JSONResponse({"code": "INVALID_LOOKUP"}, status_code=422)


@app.get("/health/live")
async def live():
    return {"status": "HEALTHY", "capability": "fixed_read_observations"}


@app.post("/api/v1/evidence/collect")
async def evidence(body: Lookup):
    if active.locked():
        raise HTTPException(429, "observation collection in progress")
    async with active:
        try:
            async with asyncio.timeout(10):
                return await collect(body)
        except Exception:
            raise HTTPException(503, "live evidence unavailable") from None


@app.get("/api/v1/evidence/calls")
async def calls(query: Annotated[CallQuery, Query()]):
    async with asyncio.timeout(4):
        return await list_calls(query)


@app.get("/api/v1/evidence/calls/{uid}")
@app.get("/api/v1/evidence/calls/{uid}/state")
async def detail(uid: UUID, request: Request):
    if active.locked():
        raise HTTPException(429, "evidence reader busy")
    async with active:
        try:
            async with asyncio.timeout(9):
                result = await call_detail(uid)
                if request.url.path.endswith("/state"):
                    return await call_state(result)
                return result
        except LookupError:
            raise HTTPException(404, "CALL_NOT_OBSERVED") from None
        except EvidenceUnavailable:
            raise HTTPException(503, "CALL_INVENTORY_UNAVAILABLE") from None
        except Exception:
            raise HTTPException(503, "CALL_EVIDENCE_UNAVAILABLE") from None
