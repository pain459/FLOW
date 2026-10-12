"""Fixed-target localhost ingress; no credentials, evidence or model access."""

import re

import httpx
from fastapi import FastAPI, Request
from starlette.responses import Response, JSONResponse

from decision_engine.http_limits import RequestLimits

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(RequestLimits, timeout_seconds=12)
UPSTREAM = "http://incident-controller:8092"
PATH = re.compile(
    r"/(?:assets/[a-z.-]+|health/(?:live|ready)|api/v1/intelligence/[a-zA-Z0-9/_-]+)?"
)


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def forward(request: Request, path: str):
    if not PATH.fullmatch(request.url.path):
        return JSONResponse({"code": "NOT_FOUND"}, 404)
    query = str(request.url.query)
    if len(query) > 1024:
        return JSONResponse({"code": "INVALID_QUERY"}, 422)
    headers = {
        name: request.headers[name]
        for name in ("authorization", "idempotency-key", "content-type")
        if name in request.headers
    }
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            async with client.stream(
                request.method,
                UPSTREAM + request.url.path,
                params=query,
                headers=headers,
                content=await request.body(),
            ) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 1024**2:
                        return JSONResponse({"code": "RESPONSE_LIMIT"}, 502)
                    chunks.append(chunk)
                return Response(
                    b"".join(chunks),
                    status_code=response.status_code,
                    media_type=response.headers.get("content-type"),
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )
    except httpx.HTTPError:
        return JSONResponse({"code": "CONTROLLER_UNAVAILABLE"}, 503)
