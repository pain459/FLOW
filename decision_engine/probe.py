"""Capture real typed inference without public ports or privileged inputs."""

import asyncio
import json
import time
from pathlib import Path

import httpx

from decision_engine.models.observation import from_snapshot
from decision_engine.providers.laya_provider import LayaProvider
from decision_engine.questions.catalog import questions


async def main():
    provider = LayaProvider()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            health = await provider.health()
            if health["status"] == "HEALTHY":
                break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    else:
        raise RuntimeError("model readiness deadline")
    snapshot = json.loads(next(Path("/public").glob("*/latest.json")).read_text())
    state = from_snapshot(snapshot).model_dump(mode="json")
    samples = []
    for _ in range(3):
        answer = await provider.decide(state, questions())
        samples.append(answer)
    result = {
        "provider_health": health,
        "input_kind": "recorded_sanitized_snapshot",
        "first_inference_ms": samples[0]["inference_ms"],
        "warm_inference_ms": [v["inference_ms"] for v in samples[1:]],
        "samples": samples,
    }
    Path("/reports/provider-probe.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}))


if __name__ == "__main__":
    asyncio.run(main())
