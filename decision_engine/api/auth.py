"""Local operator session; bearer CLI remains supported. No browser token storage."""

import hashlib
import hmac
import os
import secrets
import time

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import Field

from decision_engine.models.contracts import StrictModel

COOKIE = "pulsepay_operator"
TTL = 8 * 3600
router = APIRouter(prefix="/api/v1/intelligence/auth")


def secret():
    return os.environ.get("DECISION_API_TOKEN", "unprovisioned").encode()


def signature(payload):
    return hmac.new(
        secret(), ("operator-session-v1:" + payload).encode(), hashlib.sha256
    ).hexdigest()


def valid_cookie(value):
    try:
        expires, nonce, sig = value.split(".")
        return (
            len(nonce) == 32
            and nonce.isalnum()
            and int(time.time()) < int(expires) <= int(time.time()) + TTL
            and hmac.compare_digest(sig, signature(expires + "." + nonce))
        )
    except (ValueError, TypeError, AttributeError):
        return False


def same_origin(request):
    expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
    if (
        request.headers.get("origin") != expected
        or request.headers.get("x-requested-with") != "PulsePay"
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise HTTPException(403, "SAME_ORIGIN_REQUIRED")


async def operator(request: Request, authorization: str = Header(default="")):
    if authorization:
        if hmac.compare_digest(authorization.encode(), b"Bearer " + secret()):
            return "local-operator"
        raise HTTPException(401, "operator authorization required")
    if valid_cookie(request.cookies.get(COOKIE)):
        if request.method != "GET":
            same_origin(request)
        return "local-operator"
    raise HTTPException(401, "operator authorization required")


class Login(StrictModel):
    token: str = Field(min_length=1, max_length=128)


@router.get("/session")
async def status(request: Request):
    return {
        "authorized": valid_cookie(request.cookies.get(COOKIE)),
        "expires_in_seconds": TTL,
        "analysis": "explicit_request_only",
    }


@router.post("/session")
async def login(body: Login, request: Request, response: Response):
    same_origin(request)
    if not hmac.compare_digest(body.token.encode(), secret()):
        raise HTTPException(401, "operator authorization required")
    payload = str(int(time.time()) + TTL) + "." + secrets.token_hex(16)
    response.set_cookie(
        COOKIE,
        payload + "." + signature(payload),
        max_age=TTL,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/api/v1/intelligence",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authorized": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    same_origin(request)
    response.delete_cookie(COOKIE, path="/api/v1/intelligence", httponly=True, samesite="strict")
    return {"authorized": False}
