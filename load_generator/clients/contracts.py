import json
from pydantic import BaseModel, ValidationError
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout,
)
from apps.pulsepay.schemas.accounts import (
    AccountResponse,
    BalanceResponse,
    SummaryResponse,
    LedgerPage,
)
from apps.pulsepay.schemas.transfers import TransferResponse

BUSINESS_CODES = {
    "INSUFFICIENT_FUNDS": 422,
    "INVALID_TRANSFER": 422,
    "ACCOUNT_INACTIVE": 409,
    "IDEMPOTENCY_CONFLICT": 409,
}
MODELS: dict[str, type[BaseModel]] = {
    "account_read": AccountResponse,
    "balance_read": BalanceResponse,
    "summary_read": SummaryResponse,
    "history_read": LedgerPage,
    "transfer_write": TransferResponse,
    "transfer_status": TransferResponse,
}


def transport_error_class(error: Exception | None) -> str:
    """Controlled diagnostics; exception text can contain URLs or credentials."""
    if isinstance(error, Timeout):
        return "Timeout"
    if isinstance(error, RequestsConnectionError):
        return "ConnectionError"
    if isinstance(error, RequestException):
        return "RequestError"
    return "UnknownTransportError"


def classify(
    operation: str, status: int, data: dict, context: dict, error: Exception | None = None
) -> str:
    if status == 0:
        return "timeout" if isinstance(error, Timeout) else "infrastructure_failure"
    if status >= 500 or status == 429:
        return "infrastructure_failure"
    if not isinstance(data, dict):
        return "contract_error"
    if status >= 400:
        if operation not in {"transfer_write", "rejection"}:
            return "contract_error"
        code = data.get("code")
        if (
            not isinstance(code, str)
            or BUSINESS_CODES.get(code) != status
            or not isinstance(data.get("message"), str)
            or not isinstance(data.get("request_id"), str)
        ):
            return "contract_error"
        if operation == "rejection" and context.get("expected_code") == code:
            return "expected_rejection"
        if operation == "rejection":
            return "contract_error"
        return "business_rejection"
    if operation == "rejection" or status not in (
        {200, 201} if operation == "transfer_write" else {200}
    ):
        return "contract_error"
    try:
        result = MODELS[operation].model_validate_json(json.dumps(data), strict=True)
        if isinstance(result, TransferResponse):
            if (
                result.status != "committed"
                or result.amount_minor <= 0
                or result.source_account_id == result.destination_account_id
            ):
                return "contract_error"
            for key in (
                "source_account_id",
                "destination_account_id",
                "amount_minor",
                "currency",
                "id",
            ):
                if key in context and str(getattr(result, key)) != str(context[key]):
                    return "contract_error"
        elif isinstance(result, LedgerPage):
            if len(result.items) > context.get("limit", 100):
                return "contract_error"
        elif isinstance(result, (AccountResponse, BalanceResponse, SummaryResponse)):
            actual_id = getattr(result, "account_id", getattr(result, "id", None))
            if (
                str(actual_id) != context.get("account_id")
                or result.currency != context.get("currency")
                or result.balance_minor < 0
            ):
                return "contract_error"
        else:
            return "contract_error"
        return "replay" if operation == "transfer_write" and status == 200 else "success"
    except (ValidationError, ValueError, TypeError, KeyError):
        return "contract_error"
