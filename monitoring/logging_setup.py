#!/usr/bin/env python3
"""
monitoring/logging_setup.py — Structured JSON application logging.

Writes one JSON object per line to ``data/logs/app.log`` with rotation
(10 MB per file, 10 backups).  Every record carries:

    timestamp, level, module, message, request_id, user_id, duration_ms

``request_id`` / ``user_id`` / ``duration_ms`` default to "-" / 0 and are
populated per-request by the API middleware via ``bind_request_context``.

Never log passwords, tokens, or other credentials through this logger.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 10  # keep 10 rotated backups

# Per-request context, set by the API middleware.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")


def bind_request_context(request_id: str, user_id: str = "-") -> None:
    """Bind request-scoped values for the JSON formatter."""
    request_id_ctx.set(request_id)
    user_id_ctx.set(user_id)


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_ctx.get(),
            "user_id": getattr(record, "user_id", None) or user_id_ctx.get(),
            "duration_ms": getattr(record, "duration_ms", 0),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_app_logger() -> logging.Logger:
    """Return the shared 'app' JSON logger, configuring handlers once."""
    logger = logging.getLogger("app")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    os.makedirs(_LOG_DIR, exist_ok=True)

    handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


app_logger = get_app_logger()
