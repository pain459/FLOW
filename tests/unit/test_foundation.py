from fastapi.testclient import TestClient


def test_liveness_requires_no_dependencies():
    from apps.pulsepay.main import app

    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "HEALTHY"


def test_config_rejects_currency():
    import pytest
    from pydantic import ValidationError
    from shared.config import Settings

    with pytest.raises(ValidationError):
        Settings(pulsepay_currency="NOT-CURRENCY")
