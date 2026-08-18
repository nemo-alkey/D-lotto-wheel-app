#!/usr/bin/env python3
"""
security_log.py — Rotating security/audit logger.

A dedicated ``security`` logger writing to ``data/logs/security.log`` with
rotation (10 MB per file, 5 backups).  Used for authentication attempts
(success and failure, with IP and timestamp) and admin actions.

Never log passwords, JWT tokens, or other credentials through this logger —
call sites pass usernames, IPs, and action metadata only.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "security.log")

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_BACKUP_COUNT = 5  # keep 5 rotated backups


def get_security_logger() -> logging.Logger:
    """Return the shared 'security' logger, configuring handlers once."""
    logger = logging.getLogger("security")
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
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


security_logger = get_security_logger()
