"""Normal lab deployment availability without bypassing fault authorization."""

import os
import subprocess
from pathlib import Path

import pytest

from chaos.authority import freeze
from chaos.tests.test_safety_guards import target
from chaos.tests.test_workbench import client, headers


@pytest.mark.parametrize("setting", [None, "true", "false"])
def test_cli_uses_compose_database_permission_without_an_extra_override(tmp_path, setting):
    """An unset shell variable must not overwrite the configured Compose permission."""
    capture = tmp_path / "arguments"
    shell = (
        "docker() {\n"
        '  if [ "$1" = image ]; then printf "sha256:test-image\\n"; return 0; fi\n'
        '  printf "%s\\n" "$@" > "$CAPTURE"\n'
        "}\n"
        '. "$(dirname "$0")/common.sh"\n'
        "chaos_cli list\n"
    )
    env = dict(os.environ, CAPTURE=str(capture))
    env.pop("ALLOW_DATABASE_CHAOS", None)
    if setting is not None:
        env["ALLOW_DATABASE_CHAOS"] = setting
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["sh", "-c", shell, "chaos/scripts/experiment.sh"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    arguments = capture.read_text().splitlines()
    assert arguments[-2:] == ["chaos-runner", "list"]
    assert not any(value.startswith("ALLOW_DATABASE_CHAOS=") for value in arguments)


def test_explicitly_disabled_database_scenario_is_unavailable_in_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_DATABASE_CHAOS", "false")
    api = client(tmp_path, monkeypatch)
    scenario = next(
        item
        for item in api.get("/api/scenarios").json()["items"]
        if item["id"] == "008-postgres-outage"
    )
    assert scenario["enabled"] is False
    assert scenario["database_opt_in"] is True
    response = api.post(
        "/api/actions/preflight",
        json={"scenario": scenario["id"]},
        headers=headers(api),
    )
    assert response.status_code == 409


def test_available_database_scenario_still_requires_run_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_DATABASE_CHAOS", "true")
    api = client(tmp_path, monkeypatch)
    token = headers(api)
    scenario = next(
        item
        for item in api.get("/api/scenarios").json()["items"]
        if item["id"] == "008-postgres-outage"
    )
    assert scenario["enabled"] is True
    response = api.post("/api/actions/run", json={"scenario": scenario["id"]}, headers=token)
    assert response.status_code == 422
    assert not api.app.state.jobs.current


@pytest.mark.parametrize("case", ["unrelated_project", "protected_target", "wrong_role"])
def test_enabled_database_permission_does_not_expand_gateway_targets(monkeypatch, case):
    monkeypatch.setenv("ALLOW_DATABASE_CHAOS", "true")
    value = target("postgres")
    if case == "unrelated_project":
        value["Config"]["Labels"]["com.docker.compose.project"] = "unrelated"
    elif case == "protected_target":
        value["Config"]["Labels"]["io.pulsepay.chaos.protected"] = "true"
    else:
        value = target("redis")
    request = {
        "run_id": "chaos-deployment-availability",
        "scenario": "008-postgres-outage",
        "configuration": {"duration_seconds": 8},
        "target_id": value["Id"],
    }
    with pytest.raises(ValueError, match="outside disposable lab|role does not match"):
        freeze(request, "chaosloop", value)
