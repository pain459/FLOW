"""Private fixed-read gateway. Only an operator request starts a collection."""

import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from decision_engine.models.live import Lookup
from decision_engine.adapters.live_evidence import collect
from decision_engine.http_limits import RequestLimits

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
