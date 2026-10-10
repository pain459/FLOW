"""Docker API client can reach only the opt-in authorization gateway."""

import json
import os
import time
import httpx
from chaos.policy import allowed_target, NETTOOLS_IMAGE, qdisc_commands

PROJECT = os.getenv("COMPOSE_PROJECT_NAME", "chaosloop")


class Docker:
    def __init__(self):
        watchdog = os.getenv("SERVICE_NAME") == "chaos-watchdog"
        headers = {}
        if watchdog:
            from pathlib import Path

            headers["Authorization"] = (
                "Bearer " + Path("/authority/watchdog-token").read_text().strip()
            )
        self.client = httpx.Client(
            base_url="http://docker-gate:" + ("2376" if watchdog else "2375"),
            headers=headers,
            timeout=10,
            trust_env=False,
        )

    def lease(self):
        return self.call("GET", "/lab/lease")

    def register(self, lease):
        return self.call(
            "POST",
            "/lab/lease",
            json={key: lease[key] for key in ("run_id", "scenario", "configuration")}
            | {"target_id": lease["target"]["Id"]},
        )

    def arm(self):
        return self.call("POST", "/lab/arm", json={})

    def revoke(self):
        return self.call("POST", "/lab/revoke", json={})

    def release(self):
        return self.call("POST", "/lab/release", json={})

    def call(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code not in (200, 201, 204, 304):
            raise RuntimeError(
                f"Restricted Docker API {response.status_code}: {path.split('?')[0]}"
            )
        return (
            response.json()
            if response.content
            and response.headers.get("content-type", "").startswith("application/json")
            else response.content
        )

    def inspect(self, identifier):
        return self.call("GET", f"/containers/{identifier}/json")

    def targets(self):
        rows = self.call("GET", "/containers/json?all=true")
        return [
            self.inspect(row["Id"])
            for row in rows
            if row.get("Labels", {}).get("io.pulsepay.chaos.target") == "true"
        ]

    def target(self, role):
        rows = [
            row
            for row in self.targets()
            if row["Config"]["Labels"].get("io.pulsepay.chaos.role") == role
        ]
        if len(rows) != 1 or not allowed_target(rows[0], PROJECT):
            raise ValueError("Exactly one label-allowlisted target is required: " + role)
        return rows[0]

    def create(self, body):
        return self.call("POST", "/containers/create", json=body)["Id"]

    def start(self, identifier):
        return self.call("POST", f"/containers/{identifier}/start")

    def helper(self, image, command, host=None, entrypoint=None):
        body = {"Image": image, "Cmd": command, "HostConfig": host or {}}
        if entrypoint:
            body["Entrypoint"] = entrypoint
        elif image == NETTOOLS_IMAGE:
            body["Entrypoint"] = [command[0]]
            body["Cmd"] = command[1:]
        identifier = self.create(body)
        self.start(identifier)
        return identifier

    def wait(self, identifier, seconds=70):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            row = self.inspect(identifier)
            if not row["State"]["Running"]:
                return row["State"]["ExitCode"]
            time.sleep(0.2)
        raise TimeoutError("Bounded injector did not exit")

    def logs(self, identifier):
        content = self.call(
            "GET", f"/containers/{identifier}/logs?stdout=true&stderr=true&tail=1000"
        )
        if not isinstance(content, bytes):
            return json.dumps(content)
        # Docker non-TTY output has eight-byte framing. Decode bounded evidence.
        parts = []
        while len(content) >= 8 and content[0] in (1, 2):
            size = int.from_bytes(content[4:8], "big")
            parts.append(content[8 : 8 + size].decode(errors="replace"))
            content = content[8 + size :]
        return "".join(parts) if parts else content.decode(errors="replace")

    def remove(self, identifier):
        return self.call("DELETE", f"/containers/{identifier}?force=true")

    def qdisc(self, target, restore=False, interface="eth0"):
        read, cleanup, _ = qdisc_commands(interface)
        identifier = self.helper(
            NETTOOLS_IMAGE,
            cleanup if restore else read,
            {"NetworkMode": "container:" + target["Id"], "CapAdd": ["NET_ADMIN"]},
        )
        try:
            code = self.wait(identifier, 10)
            output = self.logs(identifier)
            if code:
                raise RuntimeError("Owned network state check/cleanup refused")
            return output
        finally:
            self.remove(identifier)
