"""Explicit CI fixture only. Never selected by the runtime controller."""

import asyncio


class MockProvider:
    def __init__(self, fail=False, delay=0):
        self.fail, self.delay = fail, delay

    async def health(self):
        return {"status": "FIXTURE", "provider": "mock"}

    async def decide(self, state, questions):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise TimeoutError("fixture provider unavailable")
        answers = {}
        for key, q in questions.items():
            if q["type"] == "noul":
                a = {"type": "noul", "noul": 0.75, "confidence": 0.75, "answer_confidence": 0.75}
            else:
                options = (
                    list(q["criteria"])
                    if q["type"] == "choice"
                    else [str(i) for i in range(len(q["criteria"]))]
                )
                p = {k: 1 / len(options) for k in options}
                a = {
                    "type": q["type"],
                    "probabilities": p,
                    "confidence": 0.0,
                    "answer_confidence": max(p.values()),
                }
                if q["type"] == "choice":
                    a["choice"] = options[0]
                else:
                    a.update(
                        score=sum(int(k) * v for k, v in p.items()),
                        legend={str(i): label for i, label in enumerate(q["criteria"])},
                    )
            a["action"] = {"act_probability": 0.5}
            answers[key] = a
        return {
            "raw_answers": answers,
            "provider_version": "mock-fixture-v1",
            "inference_ms": self.delay * 1000,
        }
