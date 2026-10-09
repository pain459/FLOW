from uuid import uuid4
from sqlalchemy.engine import make_url
from apps.pulsepay.infrastructure.db import Database
from shared.config import Settings


async def test_database_connection_refusal_is_retryable(lab, monkeypatch):
    import apps.pulsepay.main as main

    bad = Database(
        Settings(
            database_url=make_url(main.config.database_url)
            .set(host="127.0.0.1", port=1)
            .render_as_string(hide_password=False)
        )
    )
    monkeypatch.setattr(main, "db", bad)
    try:
        response = await lab.client.get(f"/api/v1/accounts/{uuid4()}/balance")
        assert response.status_code == 503
        assert response.json()["code"] == "DATABASE_UNAVAILABLE"
        assert (await lab.client.get("/health/ready")).status_code == 503
        assert (await lab.client.get("/health/live")).status_code == 200
    finally:
        await bad.close()


async def test_chunked_body_is_bounded(lab):
    async def chunks():
        yield b" " * 20000
        yield b"{}"

    result = await lab.client.post(
        "/api/v1/accounts",
        content=chunks(),
        headers={"Content-Type": "application/json", "X-Request-ID": "size-limit-test"},
    )
    assert result.status_code == 413
    assert result.json()["request_id"] == "size-limit-test"


async def test_arbitrary_http_methods_have_one_bounded_metric_label(lab):
    for method in ("PROBEONE", "PROBETWO", "PROBETHREE"):
        response = await lab.client.request(method, "/health/live")
        assert response.status_code == 405
    raw = (await lab.client.get("/metrics")).text
    assert 'method="OTHER"' in raw
    assert all(method not in raw for method in ("PROBEONE", "PROBETWO", "PROBETHREE"))
