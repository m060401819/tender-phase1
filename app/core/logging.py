from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"

_REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("request_id", default=None)
_CONFIGURED = False
_RESERVED_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


def get_request_id() -> str | None:
    return _REQUEST_ID_CONTEXT.get()


def set_request_id(request_id: str | None = None) -> tuple[str, Token]:
    normalized_request_id = (request_id or "").strip() or uuid4().hex
    token = _REQUEST_ID_CONTEXT.set(normalized_request_id)
    return normalized_request_id, token


def reset_request_id(token: Token) -> None:
    _REQUEST_ID_CONTEXT.reset(token)


def build_log_extra(
    *,
    event: str,
    request_id: str | None = None,
    source_code: str | None = None,
    crawl_job_id: int | None = None,
    job_type: str | None = None,
    triggered_by: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event,
        "request_id": request_id or get_request_id(),
        "source_code": source_code,
        "crawl_job_id": crawl_job_id,
        "job_type": job_type,
        "triggered_by": triggered_by,
    }
    payload.update(fields)
    return {key: value for key, value in payload.items() if value is not None}


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        record_request_id = getattr(record, "request_id", None) or get_request_id()
        if record_request_id is not None:
            payload["request_id"] = record_request_id

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS or value is None:
                continue
            if key == "request_id":
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text

        return json.dumps(payload, ensure_ascii=False, default=_json_default)


def configure_logging(*, level: int = logging.INFO, force: bool = False) -> None:
    global _CONFIGURED

    if _CONFIGURED and not force:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonLogFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(level)

    _CONFIGURED = True


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    return str(value)
