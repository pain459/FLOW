import asyncio
import json
from uuid import uuid4, uuid5, NAMESPACE_URL
import httpx
from shared.config import Settings


async def main():
    config = Settings()
    async with httpx.AsyncClient(base_url="http://api:8080", timeout=10) as c:
        assert (await c.get("/health/live")).status_code == 200
        assert (await c.get("/health/ready")).status_code == 200
        ids = [str(uuid5(NAMESPACE_URL, f"pulsepay:{config.seed_version}:{i}")) for i in (0, 1)]
        for endpoint in ("", "/balance", "/transactions?limit=5", "/summary"):
            assert (await c.get("/api/v1/accounts/" + ids[0] + endpoint)).status_code == 200
        key = "smoke-" + uuid4().hex
        payload = {
            "source_account_id": ids[0],
            "destination_account_id": ids[1],
            "amount_minor": 1,
            "currency": config.pulsepay_currency,
        }
        a = await c.post("/api/v1/transfers", json=payload, headers={"Idempotency-Key": key})
        b = await c.post("/api/v1/transfers", json=payload, headers={"Idempotency-Key": key})
        assert (a.status_code, b.status_code) == (201, 200)
        assert a.json()["id"] == b.json()["id"]
        assert (await c.get("/api/v1/transfers/" + a.json()["id"])).status_code == 200
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "transfer_id": a.json()["id"],
                    "request_id": a.headers["X-Request-ID"],
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
