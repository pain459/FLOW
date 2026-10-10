"""Default-deny Docker API authorization proxy, isolated from application networks.

Only this service holds the host socket. It neither selects experiments nor
sequences faults; it authorizes the frozen lease and pinned Pumba helpers.
"""

import http.client
import json
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote, parse_qs
from chaos.policy import (
    PROJECTS,
    allowed_target,
    validate_helper,
    lease_fresh,
    PUMBA_IMAGE,
    NETTOOLS_IMAGE,
    STRESS_IMAGE,
    SCENARIOS,
    qdisc_commands,
    vetted_netem_exec,
    safe_exec_start,
)
from chaos import state, authority

PROJECT = os.getenv("COMPOSE_PROJECT_NAME", "chaosloop")
SOCKET = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
MUTATION_LOCK = threading.RLock()
AUTHORITY = authority.AUTHORITY
REVOKED = set()


def current_lease():
    lease = authority.active(AUTHORITY)
    if lease and lease["run_id"] in REVOKED:
        lease["revoked"] = True
    return lease


def recover_authority():
    # Restart never renews injection authority. A surviving lease permits
    # cleanup only, even if the private volume cannot persist a revocation.
    lease = current_lease()
    if lease and not lease.get("restored"):
        REVOKED.add(lease["run_id"])
        lease["revoked"] = True
        try:
            authority.save(lease, AUTHORITY)
        except OSError:
            pass


def watchdog_fresh(lease):
    return authority.watchdog_fresh(lease, AUTHORITY)


def mirror_lease(lease):
    # Never write through a runner-owned mailbox: symlink traversal could
    # otherwise let it corrupt the separate private authority volume.
    return lease


def audit(name, **details):
    record = {"timestamp": state.now(), "event": name, **details}
    print(json.dumps(record), flush=True)
    lease = current_lease()
    if lease:
        try:
            with (AUTHORITY / lease["run_id"] / "audit.jsonl").open("a") as file:
                file.write(json.dumps(record) + "\n")
        except OSError:
            print('{"event":"authority_audit_write_failed"}', flush=True)


def injection_guard(lease):
    if not lease:
        raise ValueError("No frozen authorization lease")
    root = state.CONTROL / lease["run_id"]
    if (
        not lease.get("armed")
        or lease.get("revoked")
        or lease["run_id"] in REVOKED
        or time.time() >= lease["expires_epoch"]
        or time.time() >= lease.get("fault_deadline_epoch", float("inf"))
    ):
        raise ValueError("Injection authorization expired or revoked")
    stamp = state.heartbeat_epoch(root)
    if (
        not lease.get("armed")
        or lease.get("revoked")
        or lease["run_id"] in REVOKED
        or not lease_fresh(lease, stamp)
        or not watchdog_fresh(lease)
        or (root / "abort").exists()
        or (root / "watchdog-triggered.json").exists()
    ):
        raise ValueError(
            "Injection requires a fresh independent watchdog and unrevoked bounded lease"
        )


def mark_injection(netem=False):
    lease = current_lease()
    injection_guard(lease)
    lease["injection_started"] = True
    if "fault_deadline_epoch" not in lease:
        lease["fault_started_epoch"] = time.time()
        lease["fault_deadline_epoch"] = min(
            lease["expires_epoch"], time.time() + lease["configuration"]["duration_seconds"] + 15
        )
    if netem:
        if not lease.get("qdisc_before"):
            raise ValueError("Gateway-confirmed clean qdisc baseline required")
        lease["netem_pending"] = True
    authority.save(lease, AUTHORITY)


def record_clean_qdisc(run_id, text):
    with MUTATION_LOCK:
        lease = current_lease()
        if (
            not lease
            or lease["run_id"] != run_id
            or lease.get("armed")
            or lease.get("revoked")
            or time.time() >= lease["expires_epoch"]
        ):
            raise ValueError("Qdisc probe authorization changed while reading helper logs")
        lease["qdisc_before"] = text
        authority.save(lease, AUTHORITY)


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(SOCKET)


def upstream(method, path, body=None, stream=False):
    connection = UnixConnection("localhost", timeout=75 if stream else 10)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if stream:
        headers.update(Connection="Upgrade", Upgrade="tcp")
    connection.request(method, path, payload, headers)
    response = connection.getresponse()
    if stream and response.status == 101:
        return connection, response
    data = response.read()
    status = response.status
    content_type = response.getheader("Content-Type", "application/octet-stream")
    connection.close()
    return status, content_type, data


def docker_json(path):
    code, _, body = upstream("GET", path)
    if code != 200:
        raise ValueError("Scoped Docker object is unavailable")
    return json.loads(body)


def objects():
    rows = docker_json("/containers/json?all=true")
    result = []
    for row in rows:
        labels = row.get("Labels", {}) or {}
        if (
            labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.service")
            in {"api", "event-worker", "redis", "postgres"}
            and labels.get("io.pulsepay.lab") == "disposable"
            and labels.get("io.pulsepay.chaos.target") == "true"
            and labels.get("io.pulsepay.chaos.protected") != "true"
        ):
            result.append(row)
        elif (
            labels.get("io.pulsepay.chaos.helper") == "true"
            and labels.get("io.pulsepay.chaos.project") == PROJECT
        ):
            result.append(row)
    return result


def inspect(identifier):
    if not re.fullmatch(r"[a-f0-9]{64}", identifier):
        raise ValueError("Full immutable container ID required")
    row = docker_json("/containers/" + identifier + "/json")
    labels = row.get("Config", {}).get("Labels", {}) or {}
    helper = (
        labels.get("io.pulsepay.chaos.helper") == "true"
        and labels.get("io.pulsepay.chaos.project") == PROJECT
    )
    if not allowed_target(row, PROJECT) and not helper:
        raise ValueError("Container is outside the lab allowlist")
    return row, helper


def sanitize_inspect(row):
    result = {
        key: row.get(key)
        for key in (
            "Id",
            "Name",
            "Image",
            "State",
            "RestartCount",
            "Created",
            "NetworkSettings",
        )
    }
    config = row.get("Config", {})
    result["Config"] = {
        key: config.get(key) for key in ("Labels", "Image", "StopSignal", "Cmd", "Entrypoint")
    }
    host = row.get("HostConfig", {})
    result["HostConfig"] = {
        key: host.get(key)
        for key in (
            "RestartPolicy",
            "Memory",
            "NanoCpus",
            "CgroupParent",
            "NetworkMode",
            "CapAdd",
            "ReadonlyRootfs",
            "PidsLimit",
        )
    }
    routes = {}
    for entry in config.get("Env", []):
        key, _, value = entry.partition("=")
        if key in ("DATABASE_URL", "REDIS_URL"):
            parsed = urlsplit(value)
            routes[key] = {"host": parsed.hostname, "port": parsed.port}
    result["PulsePayDependencyRoutes"] = routes
    return result


def authorization(identifier, operation, body=None):
    row, helper = inspect(identifier)
    lease = current_lease()
    if helper:
        run = row["Config"]["Labels"]["io.pulsepay.chaos.run"]
        if run != "capability-probe" and (not lease or run != lease["run_id"]):
            raise ValueError("Helper belongs to a different experiment")
        purpose = row["Config"]["Labels"].get("io.pulsepay.chaos.purpose")
        if operation == "inject_exec":
            if purpose != "network_inject":
                raise ValueError("Read/restore helpers cannot execute injecting plans")
            injection_guard(lease)
        if operation == "start" and purpose in (
            "pumba_inject",
            "network_inject",
            "stress_inject",
        ):
            injection_guard(lease)
        return row, helper
    if not lease or lease["target"]["Id"] != identifier:
        raise ValueError("Mutation requires the frozen target lease")
    if (
        not allowed_target(row, PROJECT)
        or row["Config"]["Labels"] != lease["target"]["Config"]["Labels"]
        or row["Name"] != lease["target"]["Name"]
    ):
        raise ValueError("Target labels changed after preflight")
    if operation in ("start", "unpause"):
        return row, helper
    if operation == "update" and body == {
        "RestartPolicy": lease["target"]["HostConfig"]["RestartPolicy"]
    }:
        return row, helper
    injection_guard(lease)
    return row, helper


def register_lease(body):
    if current_lease():
        raise ValueError("An authorization lease already exists")
    target, helper = inspect(body["target_id"])
    if helper:
        raise ValueError("A helper cannot be a fault target")
    lease = authority.freeze(body, PROJECT, sanitize_inspect(target))
    kind = SCENARIOS[lease["scenario"]][1]
    if kind == "stress" and docker_json("/info").get("CgroupDriver") != "cgroupfs":
        raise ValueError("Scoped CPU child cgroup unsupported")
    if kind in ("toxic", "partition"):
        from chaos.adapters import toxiproxy

        name = "api_postgres" if kind == "toxic" else "clients_redis"
        lease["proxy_before"] = toxiproxy.runtime_snapshot(name)
        required = "DATABASE_URL" if kind == "toxic" else "REDIS_URL"
        roles = {"api"} if kind == "toxic" else {"api", "event-worker", "outbox-relay"}
        rows = docker_json("/containers/json?all=true")
        for role in roles:
            matches = [
                row
                for row in rows
                if row.get("Labels", {}).get("com.docker.compose.project") == PROJECT
                and row.get("Labels", {}).get("com.docker.compose.service") == role
            ]
            if len(matches) != 1:
                raise ValueError("Exactly one explicitly routed dependency client required")
            inspected = docker_json("/containers/" + matches[0]["Id"] + "/json")
            route = sanitize_inspect(inspected)["PulsePayDependencyRoutes"].get(required, {})
            if route.get("host") != "toxiproxy" or route.get("port") != (
                15432 if kind == "toxic" else 16379
            ):
                raise ValueError("All selected dependency clients must explicitly use the proxy")
    authority.save(lease, AUTHORITY)
    mirror_lease(lease)
    return lease


def cgroup_proof():
    """Collect a read-only scope diagnostic; ambiguous samples never enable stress."""
    lease = current_lease()
    if (
        not lease
        or lease["armed"]
        or lease["revoked"]
        or SCENARIOS[lease["scenario"]][1] != "stress"
    ):
        raise ValueError("CPU scope probe requires an unarmed CPU scenario")
    target_id = lease["target"]["Id"]
    if (
        sum(row.get("Labels", {}).get("io.pulsepay.chaos.helper") == "true" for row in objects())
        >= 4
    ):
        raise ValueError("Helper storage/concurrency ceiling reached")
    if docker_json("/info").get("CgroupDriver") != "cgroupfs" or lease["target"]["HostConfig"].get(
        "CgroupParent"
    ):
        raise ValueError("This proof supports only the discovered default cgroupfs hierarchy")

    def memory(identifier):
        return (
            docker_json("/containers/" + identifier + "/stats?stream=false")
            .get("memory_stats", {})
            .get("usage")
        )

    baseline = memory(target_id)
    body = validate_helper(
        {
            "Image": NETTOOLS_IMAGE,
            "Entrypoint": ["tail"],
            "Cmd": ["-f", "/dev/null"],
            "HostConfig": {
                "NetworkMode": "none",
                "CgroupParent": "/docker/" + target_id,
            },
        },
        lease,
        PROJECT,
    )
    code, _, result = upstream("POST", "/containers/create", body)
    if code != 201:
        raise ValueError("Read-only cgroup scope helper could not be created")
    identifier = json.loads(result)["Id"]
    helper_memory, during, after, actual_parent = None, None, None, None
    try:
        upstream("POST", "/containers/" + identifier + "/start")
        actual_parent = docker_json("/containers/" + identifier + "/json")["HostConfig"][
            "CgroupParent"
        ]
        time.sleep(0.5)
        helper_memory = memory(identifier)
        during = memory(target_id)
    finally:
        upstream("DELETE", "/containers/" + identifier + "?force=true&v=false")
        time.sleep(0.5)
        after = memory(target_id)
    # Docker's HostConfig echoes a request and concurrent memory deltas can
    # coincide. Neither establishes kernel cgroup membership or containment.
    # Keep CPU stress disabled until a dedicated kernel proof is available.
    supported = False
    proof = {
        "supported": supported,
        "target_memory_before": baseline,
        "target_memory_during": during,
        "target_memory_after": after,
        "helper_memory_bytes": helper_memory,
        "actual_child_parent": actual_parent,
        "source": "Docker configuration and memory samples; helper is tail only, no stressors",
        "kernel_membership_verified": False,
        "observed_at": state.now(),
        "reason": "KERNEL_CGROUP_MEMBERSHIP_UNVERIFIED",
    }
    lease["cgroup_proof"] = proof
    authority.save(lease, AUTHORITY)
    return proof


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def log_message(self, *args):
        pass

    def reply(self, code, value, content_type="application/json"):
        data = json.dumps(value).encode() if not isinstance(value, bytes) else value
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def handle_api(self):
        request = urlsplit(self.path)
        path = re.sub(r"^/v1\.\d+", "", unquote(request.path))
        method = self.command
        try:
            watchdog_auth = (
                self.headers.get("Authorization")
                == "Bearer " + (AUTHORITY / "watchdog-token").read_text().strip()
                if (AUTHORITY / "watchdog-token").exists()
                else False
            )
            if getattr(getattr(self, "server", None), "watchdog_only", False) and not watchdog_auth:
                raise ValueError("Private watchdog listener requires independent authority")
            if len(self.path) > 2048 or ".." in path or unquote(path) != path:
                raise ValueError("Malformed Docker path")
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 16384 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Bounded JSON bodies only")
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            if length and len(raw) != length:
                raise ValueError("Incomplete bounded JSON body")
            if path.startswith("/lab/"):
                with MUTATION_LOCK:
                    lease = current_lease()
                    if method == "GET" and path == "/lab/lease":
                        return self.reply(200, lease)
                    if method == "GET" and path == "/lab/audit" and lease:
                        record = AUTHORITY / lease["run_id"] / "audit.jsonl"
                        return self.reply(
                            200,
                            {
                                "records": record.read_text().splitlines()[-2000:]
                                if record.exists()
                                else []
                            },
                        )
                    if method == "GET" and path == "/lab/capabilities":
                        info = docker_json("/info")
                        prior = state.read(AUTHORITY / "netem-capability.json", {})
                        return self.reply(
                            200,
                            {
                                "pause": "SUPPORTED",
                                "stop": "SUPPORTED",
                                "netem": "SUPPORTED"
                                if prior.get("supported")
                                and time.time() - prior.get("epoch", 0) < 3600
                                else "REQUIRES_NAMESPACE_PROBE",
                                "stress": "REQUIRES_TARGET_CGROUP_PROOF"
                                if info.get("CgroupDriver") == "cgroupfs"
                                else "UNSUPPORTED_CGROUP_DRIVER",
                                "toxic": "REQUIRES_EXPLICIT_ROUTING",
                                "partition": "REQUIRES_EXPLICIT_ROUTING",
                            },
                        )
                    if method == "POST" and path == "/lab/lease":
                        return self.reply(201, register_lease(body))
                    if method == "POST" and path == "/lab/cgroup-proof" and body == {}:
                        return self.reply(200, cgroup_proof())
                    if method == "POST" and path == "/lab/watchdog" and watchdog_auth and lease:
                        if body != {}:
                            raise ValueError("Watchdog accepts no arbitrary fields")
                        authority.private_write(
                            AUTHORITY / lease["run_id"] / "watchdog-armed.json",
                            {"epoch": time.time()},
                        )
                        return self.reply(200, {"acknowledged": True})
                    if method == "POST" and path == "/lab/arm" and lease and body == {}:
                        if (
                            lease["armed"]
                            or lease["revoked"]
                            or time.time() >= lease["expires_epoch"]
                            or not watchdog_fresh(lease)
                        ):
                            raise ValueError("Lease cannot be rearmed or extended")
                        if SCENARIOS[lease["scenario"]][1] == "netem" and not lease.get(
                            "qdisc_before"
                        ):
                            raise ValueError("Clean gateway-confirmed network pre-state required")
                        lease["armed"] = True
                        authority.save(lease, AUTHORITY)
                        mirror_lease(lease)
                        return self.reply(200, lease)
                    if (
                        method == "POST"
                        and path == "/lab/interface"
                        and lease
                        and not lease["armed"]
                        and not lease["revoked"]
                    ):
                        if (
                            body not in ({"interface": "eth0"}, {"interface": "eth1"})
                            or SCENARIOS[lease["scenario"]][1] != "netem"
                        ):
                            raise ValueError("Unknown discovered application interface")
                        lease["configuration"]["interface"] = body["interface"]
                        authority.save(lease, AUTHORITY)
                        mirror_lease(lease)
                        return self.reply(200, lease)
                    if method == "POST" and path == "/lab/revoke" and lease and body == {}:
                        REVOKED.add(lease["run_id"])
                        lease["revoked"] = True
                        try:
                            authority.save(lease, AUTHORITY)
                        except OSError:
                            # Fail closed even if authority storage is full;
                            # restoration does not depend on evidence writes.
                            audit("authority_write_failed", authorization="REVOKED")
                        return self.reply(200, lease)
                    if (
                        method == "POST"
                        and path == "/lab/restored"
                        and watchdog_auth
                        and lease
                        and body == {}
                    ):
                        if not lease["revoked"]:
                            raise ValueError(
                                "Restore confirmation requires closed injection authorization"
                            )
                        lease.update(restored=True, armed=False)
                        authority.save(lease, AUTHORITY)
                        return self.reply(200, lease)
                    if method == "POST" and path == "/lab/release" and lease and body == {}:
                        if lease["armed"] or (lease["revoked"] and not lease.get("restored")):
                            raise ValueError(
                                "Independent restoration acknowledgement required before release"
                            )
                        if any(
                            row.get("Labels", {}).get("io.pulsepay.chaos.run") == lease["run_id"]
                            for row in objects()
                        ):
                            raise ValueError("Scoped helpers remain; cannot release")
                        (AUTHORITY / "active.json").unlink(missing_ok=True)
                        return self.reply(200, {"released": True})
                    if path.startswith("/lab/proxy"):
                        from chaos.adapters import toxiproxy

                        if method == "GET" and path in (
                            "/lab/proxy/api_postgres",
                            "/lab/proxy/clients_redis",
                        ):
                            return self.reply(
                                200, toxiproxy.runtime_snapshot(path.rsplit("/", 1)[1])
                            )
                        if (
                            method == "POST"
                            and lease
                            and body == {}
                            and path == "/lab/proxy/inject"
                        ):
                            injection_guard(lease)
                            if SCENARIOS[lease["scenario"]][1] not in (
                                "toxic",
                                "partition",
                            ):
                                raise ValueError("Proxy outside selected scenario")
                            mark_injection()
                            result = toxiproxy.runtime_inject(lease)
                            audit("proxy_injection_confirmed", scenario=lease["scenario"])
                            return self.reply(200, result)
                        if (
                            method == "POST"
                            and lease
                            and body == {}
                            and path == "/lab/proxy/restore"
                        ):
                            return self.reply(200, toxiproxy.runtime_restore(lease))
                    raise ValueError("Unknown lab authorization endpoint")
            if method in ("GET", "HEAD") and path in ("/_ping", "/health"):
                return self.reply(200, b"" if method == "HEAD" else b"OK", "text/plain")
            if method == "GET" and path in ("/version", "/info"):
                row = docker_json(path)
                if path == "/info":
                    row = {
                        key: row.get(key)
                        for key in (
                            "CgroupDriver",
                            "CgroupVersion",
                            "NCPU",
                            "MemTotal",
                            "OperatingSystem",
                            "Architecture",
                            "ServerVersion",
                        )
                    }
                return self.reply(200, row)
            if method == "GET" and path == "/containers/json":
                return self.reply(200, objects())
            match = re.fullmatch(r"/images/(.+)/json", path)
            if method == "GET" and match:
                images = {PUMBA_IMAGE, NETTOOLS_IMAGE, STRESS_IMAGE} | {
                    row["ImageID"] for row in objects()
                }
                if match[1] not in images:
                    raise ValueError("Image is outside pinned/scoped allowlist")
                row = docker_json(path)
                row["Config"] = {"Labels": row.get("Config", {}).get("Labels", {})}
                return self.reply(200, row)
            if method == "POST" and path == "/containers/create":
                with MUTATION_LOCK:
                    lease = current_lease()
                    checked = validate_helper(body, lease, PROJECT)
                    if checked["Labels"]["io.pulsepay.chaos.purpose"] in (
                        "pumba_inject",
                        "network_inject",
                        "stress_inject",
                    ):
                        authorization(lease["target"]["Id"], "inject")
                    active_helpers = [
                        row
                        for row in objects()
                        if row.get("Labels", {}).get("io.pulsepay.chaos.helper") == "true"
                    ]
                    if len(active_helpers) >= 4:
                        raise ValueError("Helper concurrency/storage ceiling reached")
                    code, _, result = upstream(method, path, checked)
                    audit("authorized_helper_created", image=checked["Image"], status=code)
                    return self.reply(code, result)
            match = re.fullmatch(
                r"/containers/([a-f0-9]{64})(?:/(json|stats|logs|start|stop|pause|unpause|kill|update|wait|attach|exec))?",
                path,
            )
            if match:
                identifier, operation = match.groups()
                row, helper = inspect(identifier)
                if method == "GET" and operation == "json":
                    return self.reply(200, sanitize_inspect(row))
                if method == "GET" and operation == "stats":
                    code, content_type, result = upstream(method, path + "?stream=false")
                    return self.reply(code, result, content_type)
                if method == "GET" and operation == "logs" and helper:
                    code, content_type, result = upstream(
                        method, path + "?stdout=true&stderr=true&tail=1000"
                    )
                    lease = current_lease()
                    if (
                        row["Config"]["Labels"].get("io.pulsepay.chaos.purpose") == "capability"
                        and not row["State"]["Running"]
                    ):
                        authority.private_write(
                            AUTHORITY / "netem-capability.json",
                            {
                                "supported": row["State"]["ExitCode"] == 0,
                                "epoch": time.time(),
                            },
                        )
                    read, _, _ = (
                        qdisc_commands(lease["configuration"]["interface"])
                        if lease
                        else (None, None, None)
                    )
                    effective = (row["Config"].get("Entrypoint") or []) + (
                        row["Config"].get("Cmd") or []
                    )
                    if (
                        lease
                        and not lease["armed"]
                        and not lease["revoked"]
                        and not lease.get("injection_started")
                        and SCENARIOS[lease["scenario"]][1] == "netem"
                        and effective == read
                    ):
                        chunks, raw = [], result
                        while len(raw) >= 8 and raw[0] in (1, 2):
                            length = int.from_bytes(raw[4:8], "big")
                            chunks.append(raw[8 : 8 + length])
                            raw = raw[8 + length :]
                        text = b"".join(chunks).decode(errors="replace")
                        if (
                            re.search(r"^qdisc (noqueue|fq|fq_codel|pfifo_fast) 0: root", text)
                            and "netem" not in text
                        ):
                            record_clean_qdisc(lease["run_id"], text)
                    return self.reply(code, result, content_type)
                if method == "DELETE" and operation is None and helper:
                    authorization(identifier, "remove")
                    code, content_type, result = upstream(method, path + "?force=true&v=false")
                    return self.reply(code, result, content_type)
                if method == "POST":
                    with MUTATION_LOCK:
                        _, helper = authorization(identifier, operation, body)
                    query = parse_qs(request.query)
                    if operation in (
                        "start",
                        "pause",
                        "unpause",
                        "stop",
                        "kill",
                        "update",
                    ):
                        if not helper:
                            kind = SCENARIOS[current_lease()["scenario"]][1]
                            if operation == "pause" and kind != "pause":
                                raise ValueError("Pause outside selected fault")
                            if operation in ("stop", "kill") and kind != "stop":
                                raise ValueError("Stop outside selected fault")
                            if operation == "kill" and query.get("signal") not in (
                                ["SIGTERM"],
                                ["SIGKILL"],
                            ):
                                raise ValueError("Unsupported signal")
                            if operation == "update" and body not in (
                                {
                                    "RestartPolicy": {
                                        "Name": "no",
                                        "MaximumRetryCount": 0,
                                    }
                                },
                                {
                                    "RestartPolicy": current_lease()["target"]["HostConfig"][
                                        "RestartPolicy"
                                    ]
                                },
                            ):
                                raise ValueError("Only original/temporary restart policy allowed")
                        elif operation not in ("start", "stop", "kill"):
                            raise ValueError("Unsupported helper state change")
                        if operation == "stop":
                            query = {"t": ["2"]}
                        elif operation == "kill":
                            query = {"signal": query.get("signal", ["SIGKILL"])}
                        elif query:
                            raise ValueError("Unsupported mutation query parameter")
                        suffix = (
                            "?" + "&".join(key + "=" + value[0] for key, value in query.items())
                            if query
                            else ""
                        )
                        with MUTATION_LOCK:
                            authorization(identifier, operation, body)
                            purpose = row["Config"]["Labels"].get("io.pulsepay.chaos.purpose")
                            if (
                                (
                                    helper
                                    and operation == "start"
                                    and purpose in ("pumba_inject", "stress_inject")
                                )
                                or (not helper and operation in ("pause", "kill", "stop"))
                                or (
                                    not helper
                                    and operation == "update"
                                    and body
                                    == {
                                        "RestartPolicy": {
                                            "Name": "no",
                                            "MaximumRetryCount": 0,
                                        }
                                    }
                                )
                            ):
                                mark_injection()
                            code, content_type, result = upstream(method, path + suffix, body)
                        audit(
                            "docker_mutation",
                            operation=operation,
                            container_id=identifier,
                            status=code,
                        )
                        return self.reply(code, result, content_type)
                    if operation == "exec" and helper and row["Config"]["Image"] == NETTOOLS_IMAGE:
                        injecting = vetted_netem_exec(
                            body, current_lease()["configuration"]["interface"]
                        )
                        with MUTATION_LOCK:
                            authorization(identifier, "inject_exec" if injecting else "exec")
                            if not injecting and not current_lease().get("netem_pending"):
                                raise ValueError("No owned netem plan to clean up")
                            code, content_type, result = upstream(method, path, body)
                        parsed = json.loads(result)
                        if code == 201:
                            authority.private_write(
                                AUTHORITY / "exec" / (parsed["Id"] + ".json"),
                                {"container_id": identifier, "injecting": injecting},
                            )
                        return self.reply(code, result, content_type)
                    if operation == "attach" and helper:
                        return self.stream_upstream(path + "?stream=1&stdout=1&stderr=1", body)
                    if operation == "wait" and helper:
                        code, content_type, result = upstream(
                            method, path + "?condition=not-running", body
                        )
                        return self.reply(code, result, content_type)
            match = re.fullmatch(r"/exec/([a-f0-9]{64})/(json|start)", path)
            if match:
                owner = state.read(AUTHORITY / "exec" / (match[1] + ".json"))
                if not owner:
                    raise ValueError("Unowned Docker exec")
                authorization(
                    owner["container_id"],
                    "inject_exec" if owner["injecting"] else "exec",
                )
                if method == "GET" and match[2] == "json":
                    return self.reply(200, docker_json(path))
                if method == "POST" and match[2] == "start" and safe_exec_start(body):
                    return self.stream_upstream(path, body, owner)
            raise ValueError("Docker endpoint denied by default")
        except (
            ValueError,
            RuntimeError,
            KeyError,
            TypeError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            print(
                json.dumps(
                    {
                        "event": "authorization_refused",
                        "path": path,
                        "reason": type(exc).__name__,
                        "safe_message": str(exc)[:200] if isinstance(exc, ValueError) else None,
                    }
                ),
                flush=True,
            )
            audit(
                "authorization_refused",
                method=method,
                path=path,
                reason=type(exc).__name__,
            )
            return self.reply(403, {"message": "Restricted lab Docker API refused this request"})

    def stream_upstream(self, path, body, owner=None):
        with MUTATION_LOCK:
            if owner:
                authorization(
                    owner["container_id"],
                    "inject_exec" if owner["injecting"] else "exec",
                )
                if owner["injecting"]:
                    mark_injection(netem=True)
            result = upstream("POST", path, body, stream=True)
        if len(result) == 3:
            code, content_type, data = result
            return self.reply(code, data, content_type)
        connection, response = result
        try:
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "tcp")
            self.end_headers()
            while True:
                part = response.fp.read1(65536)
                if not part:
                    break
                self.wfile.write(part)
                self.wfile.flush()
        finally:
            connection.close()
            self.close_connection = True

    do_GET = do_HEAD = do_POST = do_DELETE = handle_api


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address, handler, watchdog_only=False):
        self.watchdog_only = watchdog_only
        self.slots = threading.BoundedSemaphore(4 if watchdog_only else 8)
        super().__init__(address, handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


if __name__ == "__main__":
    if PROJECT not in PROJECTS:
        raise SystemExit("Docker gateway requires an explicitly supported disposable project")
    authority.initialize()
    recover_authority()
    threading.Thread(
        target=lambda: BoundedServer(
            ("0.0.0.0", 2376), Handler, watchdog_only=True
        ).serve_forever(),
        daemon=True,
    ).start()
    BoundedServer(("0.0.0.0", 2375), Handler).serve_forever()
