from uuid import uuid4


def test_retry_keys_and_pacing_are_bounded():
    from activity.main import Operation, pacing
    from shared.config import Settings

    config = Settings(activity_target_rps=2, activity_concurrency=2)
    assert pacing(config) == 1
    op = Operation("transfer", "POST", "/api/v1/transfers", {"amount_minor": 1}, str(uuid4()))
    assert op.headers()["Idempotency-Key"] == op.headers()["Idempotency-Key"]
    assert op.headers()["X-Request-ID"] == op.operation_id


async def test_wire_mix_matches_configured_reads(monkeypatch):
    from activity.main import Activity
    from shared.config import Settings
    import httpx

    operations = []

    async def handler(request):
        operations.append(request.method)
        return httpx.Response(
            201 if request.method == "POST" else 200, json={"balance_minor": 100000}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://api"
    ) as client:
        activity = Activity(Settings(activity_enabled=True), client)

        # Exercise operation selection without the real-time limiter.
        async def immediate(op):
            return await client.request(op.method, op.path, json=op.payload)

        monkeypatch.setattr(activity, "send", immediate)
        for _ in range(500):
            await activity.operation()
    share = operations.count("POST") / len(operations)
    assert 0.35 < share < 0.45, share
