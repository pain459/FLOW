"""Real HTTP boundary tests, including a response lost after a synthetic commit."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import UUID


def test_locust_context_reports_valid_response_and_identical_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCUST_SKIP_MONKEY_PATCH", "1")
    from locust.env import Environment
    from locust.clients import HttpSession
    from load_generator.clients.pulsepay import PulsePayClient
    from load_generator.controller.schemas import Profile
    from load_generator.tests.test_contracts import profile_values
    from load_generator.workloads.statistics import Statistics
    from load_generator.workloads.account_pool import AccountPool

    accounts = [
        {
            "id": str(UUID(int=i)),
            "currency": "INR",
            "status": "active",
            "balance_minor": "100000",
        }
        for i in (1, 2)
    ]
    attempts = []
    persisted_before_request = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body):
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            self.send(
                200,
                {
                    "account_id": accounts[0]["id"],
                    "balance_minor": 100000,
                    "currency": "INR",
                    "authoritative": True,
                    "source_updated_at": "2026-10-10T00:00:00Z",
                },
            )

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            persisted_before_request.append(
                (tmp_path / "intent-journal" / "unit-http.jsonl").is_file()
            )
            attempts.append((self.headers["Idempotency-Key"], body))
            if len(attempts) == 1:
                self.send(503, {"code": "DATABASE_UNAVAILABLE"})
            else:
                self.send(
                    200,
                    {
                        **json.loads(body),
                        "id": str(UUID(int=10)),
                        "status": "committed",
                        "committed_at": "2026-10-10T00:00:00Z",
                        "request_id": "replayed",
                    },
                )

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = Environment()
    stats = Statistics(tmp_path, "unit-http")

    def observe(name, response_time, response_length, context, **kwargs):
        stats.request(
            name,
            context.get("outcome"),
            context.get("status", 0),
            response_time,
            response_length,
            context,
        )

    environment.events.request.add_listener(observe)

    class User:
        def context(self):
            return {}

    session = HttpSession(
        f"http://127.0.0.1:{server.server_port}", environment.events.request, User()
    )
    profile = Profile.model_validate(
        {**profile_values(), "retry": {"deliberate_replay_percent": 0, "backoff_ms": 0}}
    )
    client = PulsePayClient(session, profile, stats, AccountPool(accounts, 42))
    try:
        outcome, data = client.read("balance_read", accounts[0]["id"])
        assert outcome == "success"
        assert stats.phases["warmup"]["outcomes"] == {"success": 1}
        outcome, data = client.transfer()
        assert outcome == "replay"
        assert attempts[0] == attempts[1]
        assert stats.phases["warmup"]["confirmed_commits"] == 1
        assert stats.phases["warmup"]["duplicate_replays"] == 1
        assert all(persisted_before_request)
        from load_generator.workloads.intents import read_intents

        intents = read_intents(tmp_path)
        assert len(intents) == 1
        assert next(iter(intents.values()))["terminal"]["result"] == "committed"
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_idle_client_refreshes_connection_and_preserves_active_reuse(tmp_path, monkeypatch):
    """Our idle policy replaces the socket; short idle still reuses HTTP keep-alive."""
    from http.server import ThreadingHTTPServer

    monkeypatch.setenv("LOCUST_SKIP_MONKEY_PATCH", "1")
    from locust.env import Environment
    from locust.clients import HttpSession
    from load_generator.clients import pulsepay
    from load_generator.controller.schemas import Profile
    from load_generator.tests.test_contracts import profile_values
    from load_generator.workloads.statistics import Statistics
    from load_generator.workloads.account_pool import AccountPool

    account = {
        "id": str(UUID(int=1)),
        "currency": "INR",
        "status": "active",
        "balance_minor": "100000",
    }
    accounts = [account, {**account, "id": str(UUID(int=2))}]
    ports = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            ports.append(self.client_address[1])
            encoded = json.dumps(
                {
                    "account_id": account["id"],
                    "balance_minor": 100000,
                    "currency": "INR",
                    "authoritative": True,
                    "source_updated_at": "2026-10-11T00:00:00Z",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = Environment()

    class User:
        def context(self):
            return {}

    session = HttpSession(
        f"http://127.0.0.1:{server.server_port}", environment.events.request, User()
    )
    client = pulsepay.PulsePayClient(
        session,
        Profile.model_validate(profile_values()),
        Statistics(tmp_path, "idle-http"),
        AccountPool(accounts, 42),
    )
    epoch = [100.0]
    monkeypatch.setattr(pulsepay, "monotonic", lambda: epoch[0], raising=False)
    try:
        for elapsed in (0, 1, 5, 9.1):
            epoch[0] = 100 + elapsed
            assert client.read("balance_read", account["id"])[0] == "success"
        assert ports[0] == ports[1], "An active keep-alive connection should be reused"
        assert ports[2] != ports[1], "Four seconds idle must retire the old connection"
        assert ports[3] != ports[2], "Longer idle must retire the old connection"
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_connection_reset_is_retained_as_transport_failure(tmp_path, monkeypatch):
    """A real disconnected socket must not be mislabeled as a read timeout."""
    import socket

    monkeypatch.setenv("LOCUST_SKIP_MONKEY_PATCH", "1")
    from locust.env import Environment
    from locust.clients import HttpSession
    from load_generator.clients.pulsepay import PulsePayClient
    from load_generator.controller.schemas import Profile
    from load_generator.tests.test_contracts import profile_values
    from load_generator.workloads.statistics import Statistics
    from load_generator.workloads.account_pool import AccountPool

    accounts = [
        {
            "id": str(UUID(int=i)),
            "currency": "INR",
            "status": "active",
            "balance_minor": "100000",
        }
        for i in (1, 2)
    ]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = Environment()
    stats = Statistics(tmp_path, "reset-http")

    def observe(name, response_time, response_length, context, **kwargs):
        stats.request(
            name, context["outcome"], context["status"], response_time, response_length, context
        )

    environment.events.request.add_listener(observe)

    class User:
        def context(self):
            return {}

    session = HttpSession(
        f"http://127.0.0.1:{server.server_port}", environment.events.request, User()
    )
    client = PulsePayClient(
        session, Profile.model_validate(profile_values()), stats, AccountPool(accounts, 42)
    )
    try:
        assert client.read("balance_read", accounts[0]["id"])[0] == "infrastructure_failure"
        assert stats.phases["warmup"]["outcomes"] == {"infrastructure_failure": 1}
        assert stats.errors[0]["error_class"] == "ConnectionError"
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
