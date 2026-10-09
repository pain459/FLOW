from pydantic import BaseModel
from typing import Any


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict | None = None


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (404, 409, 422, 500, 503)
}
