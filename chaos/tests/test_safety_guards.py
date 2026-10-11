import pytest
from chaos.policy import (
    allowed_target,
    validate_helper,
    bound_configuration,
    PUMBA_IMAGE,
    NETTOOLS_IMAGE,
    pumba_command,
    vetted_netem_exec,
    safe_exec_start,
    qdisc_commands,
    CAPABILITY_COMMAND,
)


def target(role="api", project="chaosloop"):
    return {
        "Id": "a" * 64,
        "Name": "/chaosloop-api-1",
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": role,
                "io.pulsepay.lab": "disposable",
                "io.pulsepay.chaos.target": "true",
                "io.pulsepay.chaos.role": role,
            }
        },
        "State": {"Running": True, "Paused": False},
    }


def test_target_allowlist_excludes_unrelated_protected_and_partial_ids():
    assert allowed_target(target(), "chaosloop")
    assert not allowed_target(target(project="production"), "chaosloop")
    assert not allowed_target(target(role="verifier"), "chaosloop")
    modified = target()
    modified["Config"]["Labels"]["io.pulsepay.chaos.protected"] = "true"
    assert not allowed_target(modified, "chaosloop")
    modified = target()
    modified["Id"] = "a" * 12
    assert not allowed_target(modified, "chaosloop")


def test_parameters_are_bounded_and_database_fault_requires_opt_in():
    with pytest.raises(ValueError):
        bound_configuration("001-api-pause", {"duration_seconds": 999})
    with pytest.raises(ValueError):
        bound_configuration("008-postgres-outage", {}, allow_database=False)
    with pytest.raises(ValueError):
        bound_configuration("all-containers", {})


def test_helper_creation_denies_host_authority_and_arbitrary_commands():
    lease = {
        "scenario": "001-api-pause",
        "target": target(),
        "configuration": {"duration_seconds": 10},
    }
    with pytest.raises(ValueError):
        validate_helper(
            {
                "Image": PUMBA_IMAGE,
                "Cmd": ["kill", "re2:.*"],
                "HostConfig": {"Privileged": True},
            },
            lease,
            "chaosloop",
        )


def test_netem_uses_cached_pinned_image_without_default_jitter():
    lease = {
        "scenario": "004-api-network-delay",
        "target": target(),
        "configuration": {"duration_seconds": 15},
    }
    command = pumba_command(lease, "chaosloop")
    assert "--pull-image=false" in command
    assert command[command.index("--jitter") + 1] == "0"
    assert command[command.index("--correlation") + 1] == "0"
    with pytest.raises(ValueError):
        validate_helper(
            {
                "Image": NETTOOLS_IMAGE,
                "Cmd": ["sh", "-c", "rm -rf /"],
                "HostConfig": {"NetworkMode": "host", "Binds": ["/:/host"]},
            },
            lease,
            "chaosloop",
        )


def test_pumba_default_console_shape_does_not_grant_helper_authority():
    lease = {
        "run_id": "chaos-test",
        "scenario": "004-api-network-delay",
        "target": target(),
        "configuration": {"duration_seconds": 15},
    }
    body = {
        "Image": NETTOOLS_IMAGE,
        "Entrypoint": ["tail"],
        "Cmd": ["-f", "/dev/null"],
        "StopSignal": "SIGKILL",
        "HostConfig": {
            "NetworkMode": "container:" + lease["target"]["Id"],
            "CapAdd": ["NET_ADMIN"],
            "ConsoleSize": [0, 0],
            "DNS": [],
            "PortBindings": {},
        },
    }
    result = validate_helper(body, lease, "chaosloop")
    assert result["HostConfig"]["CapDrop"] == ["ALL"]
    assert result["Labels"]["io.pulsepay.chaos.purpose"] == "network_inject"
    body["HostConfig"]["ConsoleSize"] = [24, 80]
    with pytest.raises(ValueError):
        validate_helper(body, lease, "chaosloop")


def test_exact_netem_exec_accepts_inert_sdk_defaults_and_rejects_authority():
    _, _, start = qdisc_commands("eth0")
    body = {
        "Cmd": start,
        "AttachStdout": True,
        "AttachStderr": True,
        "Privileged": False,
        "User": "",
        "Tty": False,
    }
    assert vetted_netem_exec(body, "eth0")
    for key, value in (
        ("Privileged", True),
        ("User", "root"),
        ("Env", ["DANGER=true"]),
    ):
        with pytest.raises(ValueError):
            vetted_netem_exec(body | {key: value}, "eth0")
    assert safe_exec_start({"Detach": False, "Tty": False, "ConsoleSize": [0, 0]})
    assert not safe_exec_start({"Detach": True})
    assert not safe_exec_start({"Privileged": True})


def test_isolated_capability_helper_cannot_select_any_host_cgroup():
    with pytest.raises(ValueError):
        validate_helper(
            {
                "Image": NETTOOLS_IMAGE,
                "Cmd": ["sh", "-c", CAPABILITY_COMMAND],
                "HostConfig": {
                    "NetworkMode": "none",
                    "CgroupParent": "/system.slice/docker.service",
                },
            },
            None,
            "chaosloop",
        )


def test_helper_body_must_be_an_object():
    import pytest
    from chaos.policy import validate_helper

    with pytest.raises(ValueError, match="object"):
        validate_helper(None, None, "chaosloop")
