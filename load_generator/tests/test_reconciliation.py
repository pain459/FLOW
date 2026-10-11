import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import UUID

import httpx
import pytest

from load_generator.workloads.idempotency import TransferIntent


@pytest.mark.parametrize("already_committed", [True, False])
def test_durable_pending_intent_reconciles_after_restart_without_double_commit(
    tmp_path, already_committed
):
    from load_generator.workloads.intents import IntentJournal, reconcile

    intent = TransferIntent.new(str(UUID(int=1)), str(UUID(int=2)), 50, "INR")
    journal = IntentJournal(tmp_path, "worker-one")
    journal.begin(intent, "measured")
    posts, keys, commits = [], [], {}
    response = {
        **json.loads(intent.body),
        "id": str(UUID(int=10)),
        "status": "committed",
        "committed_at": "2026-10-11T00:00:00Z",
        "request_id": "reconciled",
    }
    if already_committed:
        commits[intent.key] = response

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body):
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            key = self.headers["Idempotency-Key"]
            keys.append((key, self.headers["X-Request-Hash"]))
            self.send(
                200 if key in commits else 404,
                commits.get(
                    key,
                    {
                        "code": "TRANSFER_NOT_FOUND",
                        "message": "Not observed",
                        "request_id": "lookup",
                    },
                ),
            )

        def do_POST(self):
            key = self.headers["Idempotency-Key"]
            body = self.rfile.read(int(self.headers["Content-Length"]))
            posts.append((key, body))
            existed = key in commits
            commits.setdefault(key, response)
            self.send(200 if existed else 201, commits[key])

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.server_port}")
        report = reconcile(tmp_path, client=client, seconds=5)
        assert report["status"] == "COMPLETE"
        assert report["phases"]["measured"]["reconciled_commits"] == 1
        assert report["phases"]["measured"]["unresolved"] == 0
        assert keys == [(intent.key, hashlib.sha256(intent.body.encode()).hexdigest())]
        assert len(commits) == 1
        assert posts == ([] if already_committed else [(intent.key, intent.body.encode())])
        # A new process reads terminal evidence; repeated reconciliation emits no HTTP.
        again = reconcile(tmp_path, seconds=5)
        assert again["phases"]["measured"]["reconciled_commits"] == 1
        assert len(keys) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize(
    "status,data",
    [
        (503, {}),
        (200, {"status": "committed"}),
        (409, {"code": "IDEMPOTENCY_CONFLICT"}),
        (404, {"code": "TRANSFER_NOT_FOUND"}),
    ],
)
def test_unavailable_or_inconsistent_lookup_keeps_unknown_evidence(tmp_path, status, data):
    from load_generator.workloads.intents import IntentJournal, reconcile

    intent = TransferIntent.new(str(UUID(int=1)), str(UUID(int=2)), 50, "INR")
    IntentJournal(tmp_path, "worker-one").begin(intent, "measured")
    requests = []

    def answer(request):
        requests.append(request.method)
        return httpx.Response(status, json=data)

    client = httpx.AsyncClient(base_url="http://api:8080", transport=httpx.MockTransport(answer))
    report = reconcile(tmp_path, client=client, seconds=1)
    assert report["status"] in {"UNKNOWN", "INCONSISTENT"}
    assert report["phases"]["measured"]["unresolved"] == 1
    assert requests == ["GET"]
    assert (tmp_path / "intent-journal" / "worker-one.jsonl").exists()


def test_intent_storage_is_bounded_and_rejects_symlinks(tmp_path, monkeypatch):
    from load_generator.workloads import intents

    intent = TransferIntent.new(str(UUID(int=1)), str(UUID(int=2)), 50, "INR")
    journal = intents.IntentJournal(tmp_path, "worker-one")
    monkeypatch.setattr(intents, "MAX_JOURNAL_BYTES", 1)
    with pytest.raises(ValueError, match="ceiling"):
        journal.begin(intent, "measured")
    monkeypatch.setattr(intents, "MAX_JOURNAL_BYTES", 32 * 1024**2)
    journal.file.unlink()
    journal.file.symlink_to(tmp_path / "outside")
    with pytest.raises((ValueError, OSError)):
        journal.begin(intent, "measured")
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {"key": 12},
        {"kind": "terminal", "result": "committed"},
        {"kind": "terminal", "result": "reconciled", "transfer_id": "invalid"},
    ],
)
def test_malformed_durable_evidence_reports_unknown_without_network(tmp_path, record):
    from load_generator.workloads.intents import IntentJournal, reconcile

    intent = TransferIntent.new(str(UUID(int=1)), str(UUID(int=2)), 50, "INR")
    journal = IntentJournal(tmp_path, "worker-one")
    journal.begin(intent, "measured")
    if isinstance(record, dict) and record.get("kind") == "terminal":
        record = {**record, "key": intent.key, "worker": "worker-one"}
    with journal.file.open("a") as stream:
        stream.write(json.dumps(record) + "\n")
    requests = []
    client = httpx.AsyncClient(
        base_url="http://api:8080",
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(500)
        ),
    )
    report = reconcile(tmp_path, client=client, seconds=1)
    assert report["status"] == "UNKNOWN"
    assert report["reason"] == "INVALID_CLIENT_INTENT_EVIDENCE"
    assert json.loads((tmp_path / "reconciliation.json").read_text())["status"] == "UNKNOWN"
    assert requests == []


@pytest.mark.parametrize("mode", ["trickle", "header_trickle", "oversized"])
def test_reconciliation_http_has_total_deadline_and_response_ceiling(tmp_path, mode):
    import time
    from http.server import ThreadingHTTPServer
    from load_generator.workloads.intents import IntentJournal, reconcile

    intent = TransferIntent.new(str(UUID(int=1)), str(UUID(int=2)), 50, "INR")
    IntentJournal(tmp_path, "worker-one").begin(intent, "measured")
    posts = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            encoded = b'{"padding":"' + b"a" * 100000 + b'"}'
            try:
                if mode == "header_trickle":
                    for value in b"HTTP/1.0 200 OK\r\n":
                        self.wfile.write(bytes([value]))
                        self.wfile.flush()
                        time.sleep(0.15)
                    return
                self.send_response(200)
                if mode == "oversized":
                    self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                if mode == "trickle":
                    for value in encoded[:20]:
                        self.wfile.write(bytes([value]))
                        self.wfile.flush()
                        time.sleep(0.15)
                else:
                    self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            posts.append(True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{server.server_port}")
        started = time.monotonic()
        report = reconcile(tmp_path, client=client, seconds=1)
        elapsed = time.monotonic() - started
        assert elapsed < 1.5
        assert report["status"] in {"UNKNOWN", "INCONSISTENT"}
        assert report["phases"]["measured"]["unresolved"] == 1
        assert posts == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


def test_reconciliation_counts_do_not_inflate_measured_http_or_hide_failures(tmp_path):
    from load_generator.workloads.statistics import Statistics
    from load_generator.controller.reports import build_summary

    stats = Statistics(tmp_path, "worker-one")
    stats.request("balance_read", "success", 200, 10, 100, {"phase": "measured"})
    stats.request("transfer_write", "timeout", 0, 1000, 0, {"phase": "measured"})
    stats.logical("offered", 2, "measured")
    stats.logical("logical_attempts", 1, "measured")
    stats.logical("unknown_outcomes", 1, "measured")
    reconciliation = {
        "status": "COMPLETE",
        "phases": {
            "measured": {
                "intents": 1,
                "confirmed_during_run": 0,
                "reconciled_commits": 1,
                "rejected": 0,
                "unresolved": 0,
            }
        },
    }
    result = build_summary(
        {"run_id": "load-test", "profile": {"name": "nominal"}},
        stats.phases,
        {"status": "PASS"},
        {"status": "PASS"},
        10,
        [],
        reconciliation=reconciliation,
    )
    assert result["business"]["unknown_outcomes"] == 0
    assert result["business"]["unknown_outcomes_before_reconciliation"] == 1
    assert result["business"]["confirmed_commits"] == 0
    assert result["business"]["reconciled_commits"] == 1
    assert result["http"]["completed"] == 2
    assert result["http"]["failed"] == 1
    assert result["load"]["achieved_rps"] == 0.2
    assert result["result"] == "FAILED"
