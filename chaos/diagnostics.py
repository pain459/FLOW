"""Actionable, bounded preflight failures without exposing exception internals."""


class PreflightError(ValueError):
    def __init__(self, code: str, message: str, remediation: str):
        super().__init__(message)
        self.code = code
        self.remediation = remediation


def failure_details(error: Exception) -> dict:
    message = (
        str(error)[:300] if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
    )
    return {
        "reason": type(error).__name__,
        "code": getattr(error, "code", type(error).__name__),
        "message": message,
        "safe_message": message,
        "remediation": getattr(
            error,
            "remediation",
            "Inspect the retained preflight and failure evidence before retrying.",
        ),
    }
