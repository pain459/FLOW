import asyncio
import threading
import time

import httpx

from decision_engine.adapters.datasets import catalog, load
from decision_engine.providers.mock_provider import MockProvider
from decision_engine.questions.catalog import questions


async def test_cancelled_http_request_cannot_start_parallel_model_threads(monkeypatch):
    from decision_engine import model_service as service

    state = load(catalog()[0]["id"])[0][0]
    raw = await MockProvider().decide(state, questions())
    entered = threading.Event()

    class FakeRouter:
        def predict(self, *args, **kwargs):
            entered.set()
            time.sleep(0.3)
            return {"answers": raw["raw_answers"]}

    monkeypatch.setattr(service, "router", FakeRouter())
    monkeypatch.setenv("LAYA_REVISION", "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service.app), base_url="http://test"
    ) as c:
        payload = {"state": state, "actions": list(questions()["next_diagnostic_tool"]["criteria"])}
        first = asyncio.create_task(c.post("/decide", json=payload))
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        second = await c.post("/decide", json=payload)
        assert second.status_code == 429
        if service.inference_task:
            await asyncio.shield(service.inference_task)


async def test_expired_cpu_work_marks_readiness_unavailable(monkeypatch):
    from decision_engine import model_service as service

    task = asyncio.create_task(asyncio.sleep(0.1))
    monkeypatch.setattr(service, "router", object())
    monkeypatch.setattr(service, "inference_task", task)
    monkeypatch.setattr(service, "inference_started", time.monotonic() - 20, raising=False)
    try:
        assert (await service.ready()).status_code == 503
    finally:
        await task


def test_model_pin_requires_reviewed_weight_and_config_digests():
    from decision_engine.model_service import reviewed_router_arguments

    args = reviewed_router_arguments()
    pins = args["sha256_digests"]["multilingual"]
    assert (
        pins["model.safetensors"]
        == "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204"
    )
    assert (
        pins["rl_agent_config.json"]
        == "25061739243b617ad88d1219ba6f8a9c86c5881ca28df024fa2d9b3b2fcc30c6"
    )
    assert args["revision"] == "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67"
