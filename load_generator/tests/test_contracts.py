import json
from uuid import UUID
import pytest


def profile_values():
    return {
        "schema_version": 1,
        "name": "smoke",
        "seed": 42,
        "mode": "closed_loop",
        "users": 4,
        "spawn_rate_users_per_second": 4,
        "duration_seconds": 120,
        "warmup_seconds": 30,
        "mix": {"balance_read": 0.5, "transfer_write": 0.5},
    }


@pytest.mark.parametrize("code", [None, [], {}])
def test_malformed_business_error_code_is_contract_failure(code):
    from load_generator.clients.contracts import classify

    assert (
        classify(
            "transfer_write",
            422,
            {"code": code, "message": "Invalid envelope", "request_id": "test"},
            {},
        )
        == "contract_error"
    )


def test_strict_profile_contract_and_safety():
    from load_generator.controller.schemas import Profile
    from pydantic import ValidationError

    profile = Profile.model_validate(profile_values())
    assert profile.users == 4
    for change in (
        {"mix": {"balance_read": 0.7}},
        {"duration_seconds": -1},
        {"users": 151},
        {"unsupported": True},
        {"mix": {"unknown": 1}},
        {"retry": {"same_idempotency_key": False}},
        {"mode": "open_loop"},
    ):
        with pytest.raises(ValidationError):
            Profile.model_validate({**profile_values(), **change})


def test_only_internal_pulsepay_targets_are_allowed():
    from load_generator.controller.schemas import validate_target

    assert validate_target("http://api:8080") == "http://api:8080"
    for value in (
        "http://example.com",
        "http://api:8080.evil",
        "http://api:8080/path",
        "http://user:secret@api:8080",
        "http://localhost:8080",
        "https://api:8080",
    ):
        with pytest.raises(ValueError):
            validate_target(value)


def test_deterministic_funded_distinct_account_pairs():
    from load_generator.workloads.account_pool import AccountPool

    rows = [
        {
            "id": str(UUID(int=i + 1)),
            "balance_minor": "100000",
            "status": "active",
            "currency": "INR",
            "external_ref": f"seed:pulsepay-v1:{i}",
        }
        for i in range(8)
    ]
    a, b = (
        AccountPool(rows, seed=42, hot_count=3),
        AccountPool(rows, seed=42, hot_count=3),
    )
    plans = [[pool.pair() for _ in range(50)] for pool in (a, b)]
    assert plans[0] == plans[1]
    assert all(source != destination for source, destination in plans[0])
    assert len({account for pair in plans[0] for account in pair}) == 3
    with pytest.raises(ValueError):
        AccountPool([{**rows[0], "balance_minor": "0"}], seed=42)


def test_logical_transfer_retries_preserve_exact_payload_and_key():
    from load_generator.workloads.idempotency import TransferIntent

    a = TransferIntent.new("source", "destination", 9007199254740993, "INR")
    b = TransferIntent.new("source", "destination", 9007199254740993, "INR")
    assert a.key != b.key
    assert a.retry().key == a.key and a.retry().body == a.body
    assert json.loads(a.body)["amount_minor"] == 9007199254740993


def test_response_validation_never_counts_any_http_200_as_success():
    from load_generator.clients.contracts import classify

    context = {"account_id": str(UUID(int=1)), "currency": "INR"}
    assert classify("balance_read", 200, {"balance_minor": -1}, context) == "contract_error"
    assert (
        classify("transfer_write", 503, {"code": "DATABASE_UNAVAILABLE"}, {})
        == "infrastructure_failure"
    )


def test_valid_read_contract_and_unexpected_read_rejection():
    from load_generator.clients.contracts import classify

    context = {"account_id": str(UUID(int=1)), "currency": "INR"}
    data = {
        "account_id": context["account_id"],
        "currency": "INR",
        "balance_minor": 42,
        "authoritative": True,
        "source_updated_at": "2026-10-10T00:00:00Z",
    }
    assert classify("balance_read", 200, data, context) == "success"
    assert (
        classify(
            "history_read",
            422,
            {"code": "INVALID_TRANSFER", "message": "bad cursor", "request_id": "x"},
            context,
        )
        == "contract_error"
    )
    assert (
        classify(
            "transfer_write",
            422,
            {"code": "INSUFFICIENT_FUNDS", "message": "low", "request_id": "x"},
            {},
        )
        == "business_rejection"
    )
    assert (
        classify(
            "rejection",
            422,
            {"code": "INSUFFICIENT_FUNDS", "message": "low", "request_id": "x"},
            {"expected_code": "INSUFFICIENT_FUNDS"},
        )
        == "expected_rejection"
    )
    assert (
        classify("rejection", 201, {}, {"expected_code": "INSUFFICIENT_FUNDS"}) == "contract_error"
    )


@pytest.mark.parametrize(
    "error, expected",
    [
        ("connection", "infrastructure_failure"),
        ("timeout", "timeout"),
        ("missing", "infrastructure_failure"),
    ],
)
def test_transport_errors_distinguish_resets_from_timeouts(error, expected):
    from requests.exceptions import ConnectionError, ReadTimeout
    from load_generator.clients.contracts import classify

    exception = {"connection": ConnectionError(), "timeout": ReadTimeout(), "missing": None}[error]
    assert classify("balance_read", 0, {}, {}, exception) == expected
