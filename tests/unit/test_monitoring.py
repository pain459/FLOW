from telemetry.database import decode_snapshot
import pytest
from starlette.requests import Request
from apps.pulsepay.main import request_boundary
from shared import metrics
from apps.pulsepay.infrastructure.db import Database
from shared.config import Settings


def test_database_statistics_do_not_turn_absence_into_zero():
    result = decode_snapshot({"connections": 2, "max_connections": 100, "deadlocks": 0})
    assert result["connections"] == 2
    assert result["deadlocks"] == 0
    assert result["lock_waits"] is None
    assert result["connection_usage_percent"] == 2


@pytest.mark.asyncio
async def test_middleware_timeout_is_counted_as_observed_failure():
    request = Request({"type": "http", "method": "GET", "path": "/known", "headers": []})
    counter = metrics.http_requests.labels("GET", "unmatched", "5xx")
    before = counter._value.get()

    async def failed_next(request):
        raise TimeoutError()

    response = await request_boundary(request, failed_next)
    assert response.status_code == 503
    assert counter._value.get() == before + 1


@pytest.mark.asyncio
async def test_failed_checkout_checkin_cannot_make_pool_occupancy_negative():
    db = Database(Settings())
    try:
        # SQLAlchemy can emit checkin(None, ...) after failed connection
        # acquisition without a matching successful checkout event.
        db.engine.sync_engine.pool.dispatch.checkin(None, None)
        sample = metrics.pool_checked_out.collect()[0].samples[0]
        assert sample.value == db.engine.sync_engine.pool.checkedout() == 0
    finally:
        await db.close()
