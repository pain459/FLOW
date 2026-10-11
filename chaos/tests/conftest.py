import pytest


@pytest.fixture(autouse=True)
def isolated_public_observations(tmp_path, monkeypatch):
    """Fixture publications must never enter the real lab's observation volume."""
    monkeypatch.setenv("OBSERVATION_DIR", str(tmp_path / "observations"))
