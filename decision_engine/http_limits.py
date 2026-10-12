"""Bound actual request bytes, including chunked input, before JSON parsing."""

import asyncio

from starlette.responses import JSONResponse


class RequestLimits:
    def __init__(self, app, max_bytes=16384, timeout_seconds=10):
        self.app, self.max_bytes, self.timeout = app, max_bytes, timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def bounded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with asyncio.timeout(self.timeout):
                chunks, size = [], 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body = message.get("body", b"")
                    size += len(body)
                    if size > self.max_bytes:
                        return await JSONResponse({"code": "REQUEST_TOO_LARGE"}, status_code=413)(
                            scope, receive, send
                        )
                    chunks.append(body)
                    if not message.get("more_body", False):
                        break
                delivered = False

                async def buffered_receive():
                    nonlocal delivered
                    if delivered:
                        return await receive()
                    delivered = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

                await self.app(scope, buffered_receive, bounded_send)
        except Exception as exc:
            if not started:
                code = "REQUEST_TIMEOUT" if isinstance(exc, TimeoutError) else "UNAVAILABLE"
                await JSONResponse(
                    {"code": code, "error_class": type(exc).__name__}, status_code=503
                )(scope, receive, send)
