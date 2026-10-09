import contextvars
import json
import logging
from datetime import datetime, timezone
from opentelemetry import trace

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = trace.get_current_span().get_span_context()
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "service": self.service,
                "event": getattr(record, "event", record.name),
                "message": record.getMessage(),
                "request_id": request_id_var.get(),
                "trace_id": getattr(
                    record, "trace_id", format(ctx.trace_id, "032x") if ctx.is_valid else ""
                ),
                "operation_id": getattr(record, "operation_id", ""),
                "error_class": getattr(record, "error_class", ""),
            }
        )

    def __init__(self, service: str):
        super().__init__()
        self.service = service


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    logging.basicConfig(level=level, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
