import httpx


class LayaProvider:
    def __init__(self, url="http://laya-service:8010", timeout=15):
        if url != "http://laya-service:8010":
            raise ValueError("provider target outside allowlist")
        self.url, self.timeout = url, timeout

    async def decide(self, state, questions):
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(
                self.url + "/decide",
                json={
                    "state": state,
                    "actions": list(questions["next_diagnostic_tool"]["criteria"]),
                    "question_version": "first-response-v1"
                    if "likely_reason" in questions
                    else "investigation-v1",
                },
            )
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("provider response too large")
            return response.json()

    async def health(self):
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            return (await client.get(self.url + "/health/ready")).json()
