"""Bounded durable client intentions; recovery always preserves original identity.

Reconciliation is outside the measured workload. A 404 is an observation, never
proof that an earlier request cannot commit; its safe retry uses the same key.
"""

import asyncio
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path
from uuid import UUID
from typing import Any

import httpx

from apps.pulsepay.schemas.transfers import TransferRequest
from apps.pulsepay.schemas.errors import ErrorResponse
from load_generator.clients.contracts import classify
from load_generator.controller.lifecycle import atomic_json, now
from load_generator.controller.schemas import validate_target
from load_generator.workloads.idempotency import TransferIntent

MAX_JOURNAL_BYTES = 32 * 1024**2
MAX_RECORD_BYTES = 2048
MAX_INTENTS = 50000
MAX_RESPONSE_BYTES = 16 * 1024
PHASES = {"warmup", "measured", "cooldown"}


class IntentJournal:
    def __init__(self, path: Path, worker: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", worker):
            raise ValueError("Invalid intent worker identity")
        root = path / "intent-journal"
        root.mkdir(exist_ok=True)
        if root.is_symlink():
            raise ValueError("Intent journal cannot be a symlink")
        self.file = root / (worker + ".jsonl")
        self.worker = worker

    def append(self, record: dict):
        encoded = (
            json.dumps(
                {**record, "at": now(), "worker": self.worker},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        if len(encoded) > MAX_RECORD_BYTES:
            raise ValueError("Intent record exceeds its ceiling")
        fd = os.open(
            self.file, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o640
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size + len(encoded) > MAX_JOURNAL_BYTES:
                raise ValueError("Intent journal exceeds its storage ceiling")
            if os.write(fd, encoded) != len(encoded):
                raise OSError("Incomplete intent journal write")
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(self.file.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def begin(self, intent: TransferIntent, phase: str):
        if phase not in PHASES:
            raise ValueError("Invalid intent phase")
        self.append({"kind": "intent", "key": intent.key, "body": intent.body, "phase": phase})

    def resolve(self, key: str, result: str, transfer_id=None):
        self.append({"kind": "terminal", "key": key, "result": result, "transfer_id": transfer_id})


def read_intents(path: Path) -> dict:
    rows: dict[str, dict[str, Any]] = {}
    root = path / "intent-journal"
    if root.is_symlink():
        raise ValueError("Intent journal cannot be a symlink")
    files = sorted(root.glob("*.jsonl"))
    if len(files) > 4:
        raise ValueError("Intent journal worker ceiling exceeded")
    for file in files:
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JOURNAL_BYTES:
                raise ValueError("Invalid or oversized intent journal")
            while line := stream.readline(MAX_RECORD_BYTES + 1):
                if len(line) > MAX_RECORD_BYTES or not line.endswith(b"\n"):
                    raise ValueError("Incomplete or oversized intent record")
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("Intent records must be objects")
                key = record.get("key", "")
                if (
                    not isinstance(key, str)
                    or not re.fullmatch(r"load-[a-f0-9]{32}", key)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", file.stem)
                    or record.get("worker") != file.stem
                ):
                    raise ValueError("Invalid client intent identity")
                if record.get("kind") == "intent":
                    if key in rows or len(rows) >= MAX_INTENTS or record.get("phase") not in PHASES:
                        raise ValueError("Duplicated intent or intent count ceiling exceeded")
                    payload = TransferRequest.model_validate_json(record["body"])
                    canonical = json.dumps(
                        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                    )
                    if canonical != record["body"]:
                        raise ValueError("Client intent body must remain canonical")
                    rows[key] = record
                elif record.get("kind") == "terminal":
                    row = rows.get(key)
                    if (
                        not row
                        or row.get("terminal")
                        or row["worker"] != record["worker"]
                        or record.get("result") not in {"committed", "rejected", "reconciled"}
                    ):
                        raise ValueError("Invalid or conflicting terminal intent evidence")
                    if record["result"] == "rejected":
                        if record.get("transfer_id") is not None:
                            raise ValueError("Rejected intention cannot claim a commit")
                    elif (
                        not isinstance(record.get("transfer_id"), str)
                        or str(UUID(record["transfer_id"])) != record["transfer_id"]
                    ):
                        raise ValueError("Committed intention requires valid transfer identity")
                    row["terminal"] = record
                else:
                    raise ValueError("Unsupported intent evidence")
    return rows


async def bounded_json(client, method, url, *, headers, deadline, content=None):
    # An inactivity timeout cannot bound trickling headers/body. Cancellation covers
    # connect, headers and streamed body using the same absolute run deadline.
    async with asyncio.timeout(max(0, deadline - time.monotonic())):
        async with client.stream(
            method,
            url,
            headers={**headers, "Accept-Encoding": "identity"},
            content=content,
            timeout=min(5, max(0.001, deadline - time.monotonic())),
        ) as response:
            length = response.headers.get("content-length")
            if length is not None and int(length) > MAX_RESPONSE_BYTES:
                raise ValueError("Reconciliation response exceeds its ceiling")
            encoded = bytearray()
            if response.is_stream_consumed:
                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise ValueError("Reconciliation response exceeds its ceiling")
                encoded.extend(response.content)
            else:
                async for chunk in response.aiter_raw():
                    if len(encoded) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("Reconciliation response exceeds its ceiling")
                    encoded.extend(chunk)
            return response.status_code, json.loads(encoded)


async def reconcile_pending(
    path, rows, target, client, deadline, allow_retry, errors, observations
):
    retry_http_requests = 0
    async with client or httpx.AsyncClient(
        base_url=target, timeout=5, trust_env=False, follow_redirects=False
    ) as http:
        for key, row in rows.items():
            if row.get("terminal"):
                continue
            if deadline - time.monotonic() <= 0:
                errors.append("RECONCILIATION_DEADLINE")
                break
            intent = TransferIntent(key, row["body"])
            payload = json.loads(intent.body)
            headers = {
                "Idempotency-Key": key,
                "X-Request-Hash": hashlib.sha256(intent.body.encode()).hexdigest(),
                "X-Request-ID": key,
            }
            observation = {"key": key, "phase": row["phase"], "result": "UNKNOWN"}
            try:
                status, data = await bounded_json(
                    http,
                    "GET",
                    "/api/v1/transfers/by-idempotency-key",
                    headers=headers,
                    deadline=deadline,
                )
                if status == 404:
                    missing = ErrorResponse.model_validate(data, strict=True)
                    if (
                        missing.code != "TRANSFER_NOT_FOUND"
                        or not missing.message
                        or not missing.request_id
                    ):
                        raise ValueError("Invalid not-observed evidence")
                    if not allow_retry:
                        errors.append("RETRY_BLOCKED_BY_INTEGRITY_GATE")
                        observations.append(observation)
                        continue
                    # A valid 404 is only an observation. Complete the original intent
                    # once, keeping precisely its key/body; never create a new identity.
                    if deadline <= time.monotonic():
                        raise TimeoutError("Reconciliation deadline")
                    retry_http_requests += 1
                    status, data = await bounded_json(
                        http,
                        "POST",
                        "/api/v1/transfers",
                        content=intent.body,
                        headers={**headers, "Content-Type": "application/json"},
                        deadline=deadline,
                    )
                    outcome = classify("transfer_write", status, data, payload)
                else:
                    outcome = classify("transfer_status", status, data, payload)
                if outcome in {"success", "replay"}:
                    terminal = {"result": "reconciled", "transfer_id": data["id"]}
                    observation.update(result="COMMITTED", transfer_id=data["id"])
                elif outcome == "business_rejection" and data.get("code") != "IDEMPOTENCY_CONFLICT":
                    terminal = {"result": "rejected", "transfer_id": None}
                    observation["result"] = "REJECTED"
                else:
                    terminal = None
                    errors.append(
                        "INCONSISTENT_RESPONSE"
                        if outcome == "contract_error"
                        else "LOOKUP_UNAVAILABLE"
                    )
                if terminal:
                    IntentJournal(path, row["worker"]).resolve(key, **terminal)
                    row["terminal"] = terminal
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError, TimeoutError):
                errors.append("RECONCILIATION_UNAVAILABLE")
            observations.append(observation)
    return retry_http_requests


def reconcile(
    path: Path, target="http://api:8080", *, seconds=30, client=None, allow_retry=True
) -> dict:
    validate_target(target)
    if not 1 <= seconds <= 120:
        raise ValueError("Reconciliation deadline outside 1..120 seconds")
    started, deadline = now(), time.monotonic() + seconds
    errors: list[str] = []
    observations: list[dict] = []
    phases: dict[str, dict[str, int]] = {}
    retry_http_requests = 0
    try:
        rows = read_intents(path)
    except (OSError, ValueError, TypeError, KeyError):
        result: dict[str, Any] = {
            "status": "UNKNOWN",
            "reason": "INVALID_CLIENT_INTENT_EVIDENCE",
            "started_at": started,
            "finished_at": now(),
            "phases": {},
        }
        atomic_json(path / "reconciliation.json", result)
        return result
    retry_http_requests = asyncio.run(
        reconcile_pending(path, rows, target, client, deadline, allow_retry, errors, observations)
    )
    for row in rows.values():
        counts = phases.setdefault(
            row["phase"],
            {
                "intents": 0,
                "confirmed_during_run": 0,
                "reconciled_commits": 0,
                "rejected": 0,
                "unresolved": 0,
            },
        )
        counts["intents"] += 1
        outcome = row.get("terminal", {}).get("result")
        counts[
            {
                "committed": "confirmed_during_run",
                "reconciled": "reconciled_commits",
                "rejected": "rejected",
            }.get(outcome, "unresolved")
        ] += 1
    unresolved = sum(value["unresolved"] for value in phases.values())
    result = {
        "schema_version": 1,
        "status": "INCONSISTENT"
        if "INCONSISTENT_RESPONSE" in errors
        else "UNKNOWN"
        if errors or unresolved
        else "COMPLETE",
        "method": "lookup_then_same_key_replay",
        "started_at": started,
        "finished_at": now(),
        "phases": phases,
        "errors": sorted(set(errors)),
        "retry_http_requests": retry_http_requests,
        "observations": observations,
    }
    atomic_json(path / "reconciliation.json", result)
    return result
