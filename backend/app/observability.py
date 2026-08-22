"""Structured application logging with request correlation.

DocuMind logs in JSON by default so container log drivers can parse records
directly; local development can switch to a human-readable console format.
Every HTTP request carries a correlation ID (``X-Request-ID``, generated when
the client omits it) that is attached to all log records emitted while
handling that request, making it possible to follow one operation across
middleware, retrieval, and provider calls.

Privacy rules enforced here and across the app:

* request/question text is never logged - only its length;
* provider prompts and document contents are never logged;
* no tokens, passwords, connection strings, or storage paths appear in logs.
"""

import contextvars
import json
import logging
import sys
import time
import uuid

from app.config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_RESERVED_RECORD_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = [
            f" {key}={value}"
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_")
        ]
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} "
            f"[{request_id_var.get()}] {record.getMessage()}"
        )
        return base + "".join(fields)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    for noisy in ("httpx", "httpcore", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def new_request_id() -> str:
    return uuid.uuid4().hex


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    """Emit a structured event; ``fields`` must contain safe metadata only."""
    logger.log(level, event, extra={key: value for key, value in fields.items()})


def monotonic_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
