"""Offline CPU inference only. No database, telemetry or control credentials."""

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from typing import Literal

from decision_engine.models.contracts import StrictModel, normalize_answers
from decision_engine.questions.catalog import questions
from decision_engine.http_limits import RequestLimits
from decision_engine.checkpoint import REVISION, ARTIFACT_DIGESTS
from decision_engine.inference_input import live_input, verified_usage

router = None
failure = None
load_ms = None
busy = asyncio.Lock()
inference_task = None
inference_started = None
MAX_INFERENCE_SECONDS = 15


def reviewed_router_arguments():
    return {
        "device": "cpu",
        "max_loaded": 1,
        "revision": REVISION,
        "standalone_repos": True,
        "sha256_digests": {"multilingual": ARTIFACT_DIGESTS},
    }


def load():
    import torch
    from laya import Router

    torch.set_num_threads(2)
    if os.environ["LAYA_REVISION"] != REVISION:
        raise ValueError("unreviewed checkpoint revision")
    r = Router(**reviewed_router_arguments())
    r.load("multilingual")
    return r


@asynccontextmanager
async def lifespan(app):
    global router, failure, load_ms
    start = time.monotonic()
    try:
        router = await asyncio.to_thread(load)
    except Exception as exc:
        failure = type(exc).__name__
    load_ms = (time.monotonic() - start) * 1000
    yield


app = FastAPI(title="PulsePay constrained inference", lifespan=lifespan)
app.add_middleware(RequestLimits, timeout_seconds=20)


class Request(StrictModel):
    state: dict
    actions: list[str] = Field(min_length=1, max_length=8)
    question_version: Literal["investigation-v1", "first-response-v1"] = "investigation-v1"


@app.get("/health/live")
async def live():
    return {"status": "HEALTHY"}


@app.get("/health/ready")
async def ready():
    expired = (
        inference_task is not None
        and not inference_task.done()
        and inference_started is not None
        and time.monotonic() - inference_started > MAX_INFERENCE_SECONDS
    )
    healthy = router is not None and not expired
    return JSONResponse(
        {
            "status": "HEALTHY" if healthy else "UNAVAILABLE",
            "provider": "laya",
            "version": "0.4.3",
            "checkpoint": "multilingual",
            "revision": os.environ.get("LAYA_REVISION"),
            "device": "cpu",
            "load_ms": load_ms,
            "error_class": "INFERENCE_DEADLINE_EXCEEDED" if expired else failure,
        },
        status_code=200 if healthy else 503,
    )


@app.post("/decide")
async def decide(request: Request):
    global inference_task, inference_started
    from decision_engine.models.observation import ModelState

    try:
        if request.question_version == "first-response-v1":
            from decision_engine.models.live import LiveModelState
            from decision_engine.questions.first_response import questions as live_questions

            state = live_input(LiveModelState.model_validate(request.state).model_dump(mode="json"))
            q = live_questions(request.actions)
        else:
            state = ModelState.model_validate(request.state).model_dump(mode="json")
            q = questions(request.actions)
    except ValueError:
        raise HTTPException(422, "invalid inference input") from None
    if router is None:
        raise HTTPException(503, "model cache unavailable")
    if busy.locked() or inference_task is not None and not inference_task.done():
        raise HTTPException(429, "inference already in progress")
    async with busy:
        start = time.monotonic()
        try:
            inference_task = asyncio.create_task(
                asyncio.to_thread(router.predict, state, q, model="multilingual", max_len=1024)
            )
            inference_started = start
            # A caller timeout cannot cancel CPU work or authorize another thread.
            # Keep its completion visible after HTTP cancellation; caps bound the process.
            inference_task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            raw = await asyncio.wait_for(asyncio.shield(inference_task), MAX_INFERENCE_SECONDS)
            quality = (
                verified_usage(raw, state)
                if request.question_version == "first-response-v1"
                else None
            )
            answers = normalize_answers(raw, q)
        except Exception as exc:
            raise HTTPException(503, type(exc).__name__) from None
    return {
        "answers": answers,
        "raw_answers": raw["answers"],
        "question_version": request.question_version,
        "provider_version": "laya-0.4.3",
        "checkpoint_revision": os.environ["LAYA_REVISION"],
        "inference_ms": (time.monotonic() - start) * 1000,
        **({"input_quality": quality} if quality is not None else {}),
    }
