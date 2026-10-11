"""All financial operations go through Locust's real instrumented HTTP session."""

import json
from time import monotonic
from uuid import uuid4
import gevent
from load_generator.clients.contracts import classify, transport_error_class
from load_generator.workloads.idempotency import TransferIntent
from load_generator.workloads.intents import IntentJournal

# Retire idle sockets before the API's configured five-second keep-alive expiry.
MAX_CONNECTION_IDLE_SECONDS = 4.0


class PulsePayClient:
    def __init__(self, session, profile, stats, pool):
        self.session, self.profile, self.stats, self.pool = (
            session,
            profile,
            stats,
            pool,
        )
        self.transfers = []
        self.cursors = {}
        self.journal = IntentJournal(stats.path, stats.worker)
        self.last_request_finished: float | None = None

    def persist(self, method, *args, phase):
        try:
            method(*args)
        except (OSError, ValueError):
            self.stats.logical("intent_storage_failures", phase=phase)
            raise RuntimeError(
                "Durable client intent storage unavailable; no new transfer may be issued"
            ) from None

    def request(self, operation: str, method: str, path: str, context: dict, body=None, key=None):
        if (
            self.last_request_finished is not None
            and monotonic() - self.last_request_finished >= MAX_CONNECTION_IDLE_SECONDS
        ):
            self.session.close()
            self.stats.logical("idle_connection_refreshes")
        context = {
            **context,
            "phase": self.stats.phase(),
            "outcome": "contract_error",
            "request_id": key or "load-read-" + uuid4().hex,
            "body_bytes": len(body.encode()) if body else 0,
        }
        headers = {"Accept": "application/json", "X-Request-ID": context["request_id"]}
        if body:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": key})
        with self.session.request(
            method,
            path,
            name=operation,
            headers=headers,
            data=body,
            timeout=self.profile.request_timeout_seconds,
            allow_redirects=False,
            catch_response=True,
            context=context,
        ) as response:
            try:
                data = response.json()
            except (ValueError, TypeError):
                data = {}
            error = getattr(response, "error", None)
            outcome = classify(operation, response.status_code, data, context, error)
            context["outcome"] = outcome
            context["status"] = response.status_code
            if response.status_code == 0:
                context["error_class"] = transport_error_class(error)
            # HttpSession merges user context into a copy before the response is classified.
            response.request_meta["context"].update(context)
            if outcome in {"success", "replay", "expected_rejection"}:
                response.success()
            else:
                response.failure(
                    outcome + ": " + context["error_class"]
                    if response.status_code == 0
                    else outcome
                )
            self.last_request_finished = monotonic()
            return outcome, data

    def read(self, operation: str, account=None):
        account = account or self.pool.account()
        context = {"account_id": account, "currency": self.pool.currency}
        suffix = {
            "account_read": "",
            "balance_read": "/balance",
            "summary_read": "/summary",
            "history_read": "/transactions?limit=25",
        }[operation]
        if operation == "history_read":
            context["limit"] = 25
            cursor = self.cursors.pop(account, None)
            if cursor:
                from urllib.parse import quote

                suffix += "&cursor=" + quote(cursor, safe="")
        outcome, data = self.request(
            operation, "GET", f"/api/v1/accounts/{account}{suffix}", context
        )
        if operation == "history_read" and outcome == "success" and data.get("next_cursor"):
            if len(self.cursors) < 50:
                self.cursors[account] = data["next_cursor"]
        return outcome, data

    def transfer(self, pair=None):
        source, destination = pair or self.pool.pair()
        amount = self.pool.random.randint(
            self.profile.accounts.transfer_amount_minor_min,
            self.profile.accounts.transfer_amount_minor_max,
        )
        intent = TransferIntent.new(source, destination, amount, self.pool.currency)
        payload = json.loads(intent.body)
        phase = self.stats.phase()
        self.persist(self.journal.begin, intent, phase, phase=phase)
        self.stats.logical("logical_attempts", phase=phase)
        last = None
        for attempt in range(self.profile.retry.max_attempts):
            outcome, data = self.request(
                "transfer_write",
                "POST",
                "/api/v1/transfers",
                payload,
                intent.body,
                intent.key,
            )
            if outcome in {"success", "replay"}:
                self.persist(self.journal.resolve, intent.key, "committed", data["id"], phase=phase)
                self.stats.logical("confirmed_commits", phase=phase)
                self.transfers.append((data["id"], intent))
                self.transfers = self.transfers[-100:]
                if outcome == "replay":
                    self.stats.logical("duplicate_replays", phase=phase)
                if self.pool.random.random() * 100 < self.profile.retry.deliberate_replay_percent:
                    repeated, replay = self.request(
                        "transfer_write",
                        "POST",
                        "/api/v1/transfers",
                        {**payload, "id": data["id"]},
                        intent.body,
                        intent.key,
                    )
                    if repeated == "replay" and replay.get("id") == data["id"]:
                        self.stats.logical("duplicate_replays", phase=phase)
                    else:
                        self.stats.logical("replay_inconsistency", phase=phase)
                return outcome, data
            if outcome == "business_rejection":
                self.persist(self.journal.resolve, intent.key, "rejected", phase=phase)
                self.stats.logical("logical_rejections", phase=phase)
                self.stats.logical("unexpected_business_rejections", phase=phase)
                return outcome, data
            last = outcome
            if attempt + 1 < self.profile.retry.max_attempts:
                gevent.sleep(self.profile.retry.backoff_ms / 1000)
        self.stats.logical("unknown_outcomes", phase=phase)
        return last, {}

    def status(self, transfer=None):
        if transfer is None:
            if not self.transfers:
                # A status task needs a real committed ID; bootstrap with a normal balance read.
                return self.read("balance_read")
            transfer = self.pool.random.choice(self.transfers)
        transfer_id, intent = transfer
        return self.request(
            "transfer_status",
            "GET",
            "/api/v1/transfers/" + transfer_id,
            {**json.loads(intent.body), "id": transfer_id},
        )

    def journey(self):
        pair = self.pool.pair()
        outcome, balance = self.read("balance_read", pair[0])
        if outcome != "success":
            return
        outcome, data = self.transfer(pair)
        if outcome in {"success", "replay"}:
            self.status(self.transfers[-1])
            if self.pool.random.random() < 0.5:
                self.read("history_read", data["source_account_id"])

    def rejection(self):
        source, destination = self.pool.pair()
        choice = self.pool.random.randrange(3)
        if choice == 2 and self.transfers:
            _, original = self.pool.random.choice(self.transfers)
            changed = json.loads(original.body)
            changed["amount_minor"] += 1
            return self.request(
                "rejection",
                "POST",
                "/api/v1/transfers",
                {"expected_code": "IDEMPOTENCY_CONFLICT"},
                json.dumps(changed, sort_keys=True, separators=(",", ":")),
                original.key,
            )
        if choice == 0:
            amount, expected = 2**63 - 1, "INSUFFICIENT_FUNDS"
        else:
            destination, amount, expected = source, 1, "INVALID_TRANSFER"
        intent = TransferIntent.new(source, destination, amount, self.pool.currency)
        return self.request(
            "rejection",
            "POST",
            "/api/v1/transfers",
            {"expected_code": expected},
            intent.body,
            intent.key,
        )
