"""Static Docker authorization policy; Chaos Toolkit owns experiment semantics."""

import copy
import re
import time

PUMBA_IMAGE = "ghcr.io/alexei-led/pumba:1.2.1@sha256:780505fe261932765921c94a23e24bda107c72927654c26a5893a238d7708bf0"
NETTOOLS_IMAGE = "ghcr.io/alexei-led/pumba-alpine-nettools@sha256:bdcfacdd0c42f64cd280319d6dd5d3911f33425ce4a5168bb1b7de9570b72cd1"
STRESS_IMAGE = "ghcr.io/alexei-led/stress-ng:0.20.01@sha256:6f5de54261666970ce98abb2d710b6337c44575cd31c5886c63745323a7c12a2"
TOXIPROXY_IMAGE = "ghcr.io/shopify/toxiproxy:2.12.0@sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e"
ROLES = {"api", "event-worker", "redis", "postgres"}
PROJECTS = {"chaosloop", "chaosloop-chaos-test"}
# An authorization allowlist, not a second experiment format. Native YAML holds
# the actual hypothesis, method, rollback and parameters.
SCENARIOS = {
    "001-api-pause": ("api", "pause", 10),
    "002-worker-pause": ("event-worker", "pause", 20),
    "003-redis-outage": ("redis", "stop", 15),
    "004-api-network-delay": ("api", "netem", 15),
    "005-db-network-delay": ("api", "toxic", 15),
    "006-cpu-pressure": ("api", "stress", 15),
    "007-redis-network-partition": ("redis", "partition", 15),
    "008-postgres-outage": ("postgres", "stop", 8),
}
CAPABILITY_COMMAND = "tc qdisc add dev lo root netem delay 1ms && tc qdisc del dev lo root"
QDISC_READ = ["tc", "qdisc", "show", "dev", "eth0"]


def qdisc_commands(interface):
    from chaos.netem_policy import START, STOP

    if interface not in ("eth0", "eth1"):
        raise ValueError("Unknown discovered interface")
    return (
        ["tc", "qdisc", "show", "dev", interface],
        ["sh", "-ec", STOP.replace("eth0", interface)],
        ["sh", "-ec", START.replace("eth0", interface)],
    )


def vetted_netem_exec(body, interface):
    _, cleanup, start = qdisc_commands(interface)
    if body.get("Cmd") not in (start, cleanup):
        raise ValueError("Only exact pinned netem exec plans allowed")
    if any(
        not empty(value)
        for key, value in body.items()
        if key not in {"Cmd", "AttachStdout", "AttachStderr"}
    ):
        raise ValueError("Exec options cannot grant additional authority")
    return body["Cmd"] == start


def safe_exec_start(body):
    return (
        isinstance(body, dict)
        and not (set(body) - {"Detach", "Tty", "ConsoleSize"})
        and not body.get("Detach")
        and not body.get("Tty")
        and body.get("ConsoleSize") in (None, [0, 0])
    )


def allowed_target(info: dict, project: str) -> bool:
    labels = info.get("Config", {}).get("Labels", {}) or {}
    role = labels.get("com.docker.compose.service")
    return bool(
        project in PROJECTS
        and re.fullmatch(r"[a-f0-9]{64}", info.get("Id", ""))
        and role in ROLES
        and labels.get("com.docker.compose.project") == project
        and labels.get("io.pulsepay.lab") == "disposable"
        and labels.get("io.pulsepay.chaos.target") == "true"
        and labels.get("io.pulsepay.chaos.role") == role
        and labels.get("io.pulsepay.chaos.protected") != "true"
        and labels.get("com.docker.compose.oneoff", "False").lower() == "false"
    )


def bound_configuration(scenario: str, values: dict, allow_database=False) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError("Select an allowlisted committed scenario")
    if scenario == "008-postgres-outage" and not allow_database:
        raise ValueError("Database interruption requires ALLOW_DATABASE_CHAOS=true")
    result = {
        "duration_seconds": SCENARIOS[scenario][2],
        "ttl_seconds": 120,
        "delay_ms": 150,
        "interface": "eth0",
    }
    if set(values) - set(result):
        raise ValueError("Unsupported fault parameter")
    result.update(values)
    if type(result["duration_seconds"]) is not int or not 3 <= result["duration_seconds"] <= 40:
        raise ValueError("Fault duration outside 3..40 seconds")
    if type(result["ttl_seconds"]) is not int or not 60 <= result["ttl_seconds"] <= 180:
        raise ValueError("Experiment TTL outside 60..180 seconds")
    if result["duration_seconds"] + 30 >= result["ttl_seconds"]:
        raise ValueError("Fault duration must leave restoration time")
    if result["delay_ms"] != 150:
        raise ValueError("This validated netem plan permits 150ms only")
    if result["interface"] not in ("eth0", "eth1"):
        raise ValueError("Only discovered application interfaces are permitted")
    return result


def pumba_command(lease: dict, project: str, dry=False) -> list[str]:
    role, kind, _ = SCENARIOS[lease["scenario"]]
    name = lease["target"]["Name"].lstrip("/")
    seconds = lease["configuration"]["duration_seconds"]
    command = [
        "--host",
        "tcp://docker-gate:2375",
        "--json",
        "--log-level",
        "info",
        "--label",
        "com.docker.compose.project=" + project,
        "--label",
        "io.pulsepay.chaos.target=true",
        "--label",
        "io.pulsepay.chaos.role=" + role,
    ]
    if dry:
        command.append("--dry-run")
    if kind == "pause":
        command += ["pause", "--duration", f"{seconds}s", "--limit", "1", name]
    elif kind == "stop":
        command += [
            "stop",
            "--restart",
            "--duration",
            f"{seconds}s",
            "--time",
            "2",
            "--limit",
            "1",
            name,
        ]
    elif kind == "netem":
        command += [
            "netem",
            "--duration",
            f"{seconds}s",
            "--interface",
            lease["configuration"].get("interface", "eth0"),
            "--tc-image",
            NETTOOLS_IMAGE,
            "--pull-image=false",
            "--limit",
            "1",
            "delay",
            "--time",
            "150",
            "--jitter",
            "0",
            "--correlation",
            "0",
            name,
        ]
    elif kind == "stress":
        command += [
            "stress",
            "--duration",
            f"{seconds}s",
            "--stress-image",
            STRESS_IMAGE,
            "--pull-image=false",
            "--stressors",
            f"--cpu 1 --cpu-load 75 --timeout {seconds}s --metrics-brief",
            name,
        ]
    else:
        raise ValueError("Scenario uses Toxiproxy, not Pumba")
    return command


def empty(value):
    if isinstance(value, dict):
        return all(empty(v) for v in value.values())
    return value in (None, False, 0, "", [], {})


def validate_helper(body: dict | None, lease: dict | None, project: str) -> dict:
    if not isinstance(body, dict):
        raise ValueError("Helper body must be an object")
    if lease:
        bound_configuration(lease["scenario"], lease["configuration"], allow_database=True)
        role = SCENARIOS[lease["scenario"]][0]
        if (
            not allowed_target(lease["target"], project)
            or lease["target"]["Config"]["Labels"]["io.pulsepay.chaos.role"] != role
        ):
            raise ValueError("Frozen target does not match the named scenario")
    value = copy.deepcopy(body)
    host = value.get("HostConfig") or {}
    # Docker's Go SDK always serializes this inert two-element array.
    if "ConsoleSize" in host:
        if host.pop("ConsoleSize") != [0, 0]:
            raise ValueError("Interactive helper console is forbidden")
    allowed_host = {
        "NetworkMode",
        "CapAdd",
        "CapDrop",
        "SecurityOpt",
        "ReadonlyRootfs",
        "AutoRemove",
        "Memory",
        "NanoCpus",
        "PidsLimit",
        "LogConfig",
        "CgroupParent",
        "PortBindings",
        "DNS",
        "DNSOptions",
        "DNSSearch",
    }
    for key, item in host.items():
        if key not in allowed_host and not empty(item):
            raise ValueError("Forbidden helper host authority: " + key)
    for key, item in value.items():
        if key not in {
            "Image",
            "Cmd",
            "Entrypoint",
            "Labels",
            "HostConfig",
            "Env",
            "StopSignal",
            "AttachStdout",
            "AttachStderr",
        } and not empty(item):
            raise ValueError("Forbidden helper field: " + key)
    if any(not empty(host.get(key)) for key in ("PortBindings", "DNS", "DNSOptions", "DNSSearch")):
        raise ValueError("Helpers cannot publish ports or choose DNS")
    image, command = value.get("Image"), value.get("Cmd")
    effective = (value.get("Entrypoint") or []) + (command or [])
    if value.get("Env"):
        raise ValueError("Helpers cannot accept environment overrides")
    network = host.get("NetworkMode", "")
    capability = image == NETTOOLS_IMAGE and effective == [
        "sh",
        "-c",
        CAPABILITY_COMMAND,
    ]
    cgroup_probe = (
        image == NETTOOLS_IMAGE and effective == ["tail", "-f", "/dev/null"] and network == "none"
    )
    purpose = "capability"
    if capability:
        if network not in ("none", "") or host.get("CgroupParent"):
            raise ValueError("Capability probe must own its isolated namespace")
        host["NetworkMode"] = "none"
    elif cgroup_probe:
        if (
            not lease
            or SCENARIOS[lease["scenario"]][1] != "stress"
            or host.get("CgroupParent") != "/docker/" + lease["target"]["Id"]
        ):
            raise ValueError("Only a read-only probe of the exact target child cgroup is allowed")
        purpose = "cgroup_read"
    elif not lease:
        raise ValueError("No armed experiment lease")
    elif image == PUMBA_IMAGE:
        if value.get("Entrypoint") not in (None, [], ["/pumba"]):
            raise ValueError("Pumba entrypoint cannot be overridden")
        if command not in (
            pumba_command(lease, project),
            pumba_command(lease, project, True),
        ):
            raise ValueError("Only the exact leased Pumba command is allowed")
        if (
            network not in ("", project + "_chaos-control")
            or host.get("CapAdd")
            or host.get("CgroupParent")
            or value.get("Env")
        ):
            raise ValueError("Pumba can access only the private gate")
        host["NetworkMode"] = project + "_chaos-control"
        purpose = "pumba_read" if "--dry-run" in command else "pumba_inject"
    elif image == NETTOOLS_IMAGE:
        if network != "container:" + lease["target"]["Id"]:
            raise ValueError("Network helper must join the frozen target namespace")
        if value.get("Entrypoint") == ["tail"] and command == ["-f", "/dev/null"]:
            if SCENARIOS[lease["scenario"]][1] != "netem":
                raise ValueError("Network helper unavailable for this scenario")
            purpose = "network_inject"
        else:
            read, cleanup, _ = qdisc_commands(lease["configuration"]["interface"])
            if effective not in (read, cleanup, ["ip", "-j", "addr"]):
                raise ValueError("Unknown network helper command")
            purpose = "network_restore" if effective == cleanup else "network_read"
            if purpose == "network_restore" and (
                SCENARIOS[lease["scenario"]][1] != "netem" or not lease.get("netem_pending")
            ):
                raise ValueError("No experiment-owned netem state to restore")
        if host.get("CgroupParent"):
            raise ValueError("Network helper cannot select a cgroup")
    elif image == STRESS_IMAGE:
        purpose = "stress_inject"
        if not lease.get("cgroup_proof", {}).get("supported"):
            raise ValueError("CPU scope must be proven by actual child-cgroup accounting")
        seconds = lease["configuration"]["duration_seconds"]
        if SCENARIOS[lease["scenario"]][1] != "stress" or command != [
            "--cpu",
            "1",
            "--cpu-load",
            "75",
            "--timeout",
            f"{seconds}s",
            "--metrics-brief",
        ]:
            raise ValueError("Only the bounded leased CPU stressor is permitted")
        if (
            value.get("Entrypoint") != ["/stress-ng"]
            or host.get("CgroupParent") != "/docker/" + lease["target"]["Id"]
            or network not in ("", "none")
        ):
            raise ValueError("CPU stress requires proven target child cgroup")
        host["NetworkMode"] = "none"
    else:
        raise ValueError("Unpinned or unsupported helper image")
    caps = host.get("CapAdd") or []
    if caps == ["CAP_NET_ADMIN"]:
        caps = host["CapAdd"] = ["NET_ADMIN"]
    if caps and (image != NETTOOLS_IMAGE or caps != ["NET_ADMIN"]):
        known = {
            "NET_ADMIN",
            "CAP_NET_ADMIN",
            "NET_RAW",
            "CAP_NET_RAW",
            "SYS_ADMIN",
            "CAP_SYS_ADMIN",
        }
        names = (
            [value if value in known else "UNRECOGNIZED" for value in caps]
            if isinstance(caps, list)
            else ["INVALID_SHAPE"]
        )
        raise ValueError("Unsupported helper capability " + ",".join(names))
    host.update(
        Memory=64 * 1024**2,
        NanoCpus=1_000_000_000 if image == STRESS_IMAGE else 250_000_000,
        PidsLimit=32,
        ReadonlyRootfs=True,
        AutoRemove=False,
        CapDrop=["ALL"],
        SecurityOpt=["no-new-privileges:true"],
        LogConfig={"Type": "json-file", "Config": {"max-size": "1m", "max-file": "2"}},
    )
    if image == NETTOOLS_IMAGE and purpose != "cgroup_read":
        host["CapAdd"] = ["NET_ADMIN"]
    value["HostConfig"] = host
    value["Labels"] = {
        "io.pulsepay.chaos.helper": "true",
        "io.pulsepay.chaos.run": lease["run_id"] if lease else "capability-probe",
        "com.gaiaadm.pumba.skip": "true",
        "io.pulsepay.chaos.project": project,
        "io.pulsepay.chaos.purpose": purpose,
    }
    return value


def lease_fresh(lease: dict | None, heartbeat: float | None) -> bool:
    return bool(
        lease
        and heartbeat
        and time.time() < lease.get("expires_epoch", 0)
        and 0 <= time.time() - heartbeat < 15
    )
