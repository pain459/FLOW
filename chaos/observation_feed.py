"""File-backed read-only observation delivery. No probes, credentials or control."""

import json
import os
import stat
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, parse_qs

from chaos.observation_contract import (
    MAX_BYTES,
    MAX_SAMPLES,
    epoch,
    valid_run_id,
    validate_snapshot,
)


def read_file(root, identifier, name, limit=MAX_BYTES):
    """Open directories and files without following symlinks or blocking on FIFOs."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    base = os.open(root, flags | os.O_DIRECTORY)
    directory = None
    try:
        directory = os.open(identifier, flags | os.O_DIRECTORY, dir_fd=base) if identifier else base
        descriptor = os.open(name, flags, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("Unavailable observations")
            return stream.read(limit + 1)
    finally:
        if directory is not None and directory != base:
            os.close(directory)
        os.close(base)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, root, address):
        self.root = Path(root)
        self.capacity = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        data = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/health/live" and not url.query:
            self.reply(200, {"status": "HEALTHY"})
            return
        prefix = "/api/v1/observations/"
        if not url.path.startswith(prefix):
            self.reply(404, {"code": "NOT_FOUND"})
            return
        parts = url.path[len(prefix) :].split("/")
        if len(parts) not in (1, 2) or len(parts) == 2 and parts[1] != "sequence":
            self.reply(404, {"code": "NOT_FOUND"})
            return
        sequence = len(parts) == 2
        params = parse_qs(url.query, keep_blank_values=True)
        if set(params) - ({"limit"} if sequence else set()) or any(
            len(values) != 1 for values in params.values()
        ):
            self.reply(400, {"code": "INVALID_PARAMETERS"})
            return
        try:
            limit = int(params.get("limit", ["100"])[0])
            if not 1 <= limit <= MAX_SAMPLES:
                raise ValueError
        except ValueError:
            self.reply(400, {"code": "INVALID_PARAMETERS"})
            return
        identifier = parts[0]
        if identifier != "latest" and not valid_run_id(identifier):
            self.reply(404, {"code": "NOT_FOUND"})
            return
        try:
            root = cast(Server, self.server).root
            if identifier == "latest":
                pointer = json.loads(read_file(root, None, "latest.json", 256))
                if set(pointer) != {"run_id"} or not valid_run_id(pointer["run_id"]):
                    raise ValueError
                identifier = pointer["run_id"]
            if sequence:
                lines = read_file(root, identifier, "sequence.jsonl").splitlines()
                values = [
                    validate_snapshot(json.loads(line), identifier) for line in lines[-limit:]
                ]
                self.reply(
                    200,
                    {
                        "run_id": identifier,
                        "observations": values,
                        "delivered_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            else:
                value = validate_snapshot(
                    json.loads(read_file(root, identifier, "latest.json")), identifier
                )
                age = time.time() - epoch(value["observation_time"])
                self.reply(
                    200,
                    {
                        "observation": value,
                        "snapshot_age_seconds": age if age >= 0 else None,
                        "delivery_quality": "FRESH"
                        if 0 <= age <= 15
                        else "STALE"
                        if age >= 0
                        else "UNKNOWN",
                        "delivered_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.reply(503, {"code": "OBSERVATIONS_UNAVAILABLE"})

    def do_POST(self):
        self.reply(405, {"code": "READ_ONLY"})

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def log_message(self, *args):
        pass


def create_server(root, address=("0.0.0.0", 8091)):
    return Server(root, address)


if __name__ == "__main__":
    create_server(Path(os.getenv("OBSERVATION_DIR", "/observations"))).serve_forever()
