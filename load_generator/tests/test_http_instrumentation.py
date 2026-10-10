"""Real HTTP boundary tests, including a response lost after a synthetic commit."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import UUID


def test_locust_context_reports_valid_response_and_identical_retry(
    tmp_path, monkeypatch
):
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
    finally:
        session.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
