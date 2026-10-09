import asyncio
import re
from uuid import uuid4
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Scope, Receive, Send
from shared.logging import request_id_var


class RequestSizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int, timeout: float):
        self.app, self.max_bytes, self.timeout = app, max_bytes, timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        async with asyncio.timeout(self.timeout):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.max_bytes:
                    supplied = Headers(scope=scope).get("X-Request-ID", "")
                    rid = request_id_var.get() or (
                        supplied
                        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", supplied)
                        else str(uuid4())
                    )
                    response = JSONResponse(
                        {
                            "code": "INVALID_TRANSFER",
                            "message": "Request exceeds 16 KiB",
                            "request_id": rid,
                        },
                        status_code=413,
                        headers={"X-Request-ID": rid},
                    )
                    await response(scope, receive, send)
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
        sent = False

        async def bounded_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
