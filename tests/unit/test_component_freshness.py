from unittest.mock import AsyncMock

import pytest

from shared import metrics, runtime


async def test_failed_component_poll_does_not_refresh_cached_gauge_provenance(monkeypatch):
    component = AsyncMock()
    monkeypatch.setattr(runtime.time, "time", lambda: 100.0)
    await runtime.observe_component(component, "event-worker")
    component.tick.side_effect = ConnectionError("unavailable")
    monkeypatch.setattr(runtime.time, "time", lambda: 200.0)
    with pytest.raises(ConnectionError):
        await runtime.observe_component(component, "event-worker")
    samples = metrics.component_observed.collect()[0].samples
    assert next(row.value for row in samples if row.labels == {"service": "event-worker"}) == 100
