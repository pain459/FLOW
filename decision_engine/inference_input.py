"""Compact, deterministic model projection; full observations remain in the audit store."""

import hashlib
import json
from datetime import datetime

from decision_engine.models.live import LiveModelState

VERSION = "live-input-v1"


def live_input(state: dict) -> dict:
    live = LiveModelState.model_validate(state)
    calls = []
    for item in live.request_evidence:
        row = {"source": item.source, "quality": item.quality}
        if item.observed_at is not None:
            row["oldest_age_seconds"] = round(
                max(0, (live.observed_at - item.observed_at).total_seconds()), 1
            )
        for key in ("error_codes", "error_classes", "symptoms", "http_statuses"):
            values = getattr(item, key)
            if values:
                row[key] = values
        if item.matched_records is not None:
            row["matched_records"] = item.matched_records
        groups = {}
        for span in item.spans:
            group = groups.setdefault(
                span.operation,
                {
                    "samples": 0,
                    "errors": 0,
                    "unknown_error_flags": 0,
                    "max_ms": 0,
                    "services": set(),
                },
            )
            group["samples"] += 1
            group["errors"] += int(span.error is True or (span.http_status or 0) >= 400)
            group["unknown_error_flags"] += int(span.error is None and span.http_status is None)
            group["max_ms"] = max(group["max_ms"], round(span.duration_ms, 2))
            group["services"].add(span.service)
        if groups:
            row["sampled_spans"] = {
                key: {**value, "services": sorted(value["services"])}
                for key, value in sorted(groups.items())
            }
        calls.append(row)
    # Laya encodes dict insertion order. Call evidence comes before current system
    # measurements; SDK usage is checked as well, so partial input never yields an answer.
    result = {
        "call_evidence": calls,
        "unknown_values_omitted": True,
        "observed_at": live.observed_at.isoformat(),
        "window_seconds": live.window_seconds,
        "data_quality": {
            "sources": dict(sorted(live.source_quality.items())),
            "missing": live.missing,
            "source_age_seconds": {
                key: row["age_seconds"]
                for key, row in sorted(live.provenance.items())
                if row["age_seconds"] is not None
            },
        },
    }
    for key in ("api", "database", "redis", "worker", "workload", "integrity"):
        values = getattr(live, key).model_dump(mode="json", exclude_none=True)
        if key == "integrity":
            stamp = values.pop("verified_at", None)
            if stamp:
                values["age_seconds"] = round(
                    max(0, (live.observed_at - datetime.fromisoformat(stamp)).total_seconds()), 1
                )
        result[key] = values
    return result


def input_hash(state: dict) -> str:
    # Order is part of the inference contract; do not sort these keys.
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def verified_usage(raw: dict, state: dict) -> dict:
    usage = raw.get("usage")
    required = {
        "input_tokens",
        "state_tokens",
        "state_tokens_dropped",
        "truncated",
        "truncated_questions",
    }
    if not isinstance(usage, dict) or required - usage.keys():
        raise ValueError("INPUT_COMPLETENESS_UNKNOWN")
    for key in ("input_tokens", "state_tokens", "state_tokens_dropped"):
        if type(usage[key]) is not int or not 0 <= usage[key] <= 1000000:
            raise ValueError("INPUT_COMPLETENESS_UNKNOWN")
    if (
        usage["truncated"] is not False
        or usage["state_tokens_dropped"] != 0
        or usage["truncated_questions"] != []
    ):
        raise ValueError("INCOMPLETE_MODEL_INPUT")
    if usage["input_tokens"] == 0 or usage["state_tokens"] == 0:
        raise ValueError("INPUT_COMPLETENESS_UNKNOWN")
    return {
        "projection_version": VERSION,
        "input_sha256": input_hash(state),
        "input_tokens": usage["input_tokens"],
        "state_tokens": usage["state_tokens"],
        "state_tokens_dropped": 0,
        "truncated": False,
    }


def validate_quality(value: dict, state: dict | None = None) -> None:
    if not isinstance(value, dict) or set(value) != {
        "projection_version",
        "input_sha256",
        "input_tokens",
        "state_tokens",
        "state_tokens_dropped",
        "truncated",
    }:
        raise ValueError("missing or invalid input quality")
    if (
        value["projection_version"] != VERSION
        or value["truncated"] is not False
        or type(value["state_tokens_dropped"]) is not int
        or value["state_tokens_dropped"] != 0
    ):
        raise ValueError("incomplete input")
    for key in ("input_tokens", "state_tokens"):
        if type(value[key]) is not int or not 1 <= value[key] <= 1000000:
            raise ValueError("invalid token count")
    digest = value["input_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("invalid input hash")
    if state is not None and digest != input_hash(live_input(state)):
        raise ValueError("inference input differs from recorded observation")
