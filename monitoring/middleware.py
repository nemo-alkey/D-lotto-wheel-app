#!/usr/bin/env python3
"""
monitoring/middleware.py — HTTP observability middleware for the Lotto Wheel API.

setup_middleware(app) registers the metrics/access-log middleware that:

  - auto-increments http_requests_total and observes
    http_request_duration_seconds (labeled by route template),
  - tracks active users on a rolling 15-minute window,
  - appends one structured JSON line per request to data/logs/app.log
    with a request id, and propagates it via the X-Request-ID header.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import cast

import jwt
from fastapi import FastAPI, Request, Response
from jwt import PyJWTError as JWTError
from slowapi.util import get_remote_address

from auth import ALGORITHM, SECRET_KEY
from monitoring import metrics
from monitoring.logging_setup import app_logger, bind_request_context


def _decode_token(token: str) -> str | None:
    """Decode a JWT and return the username, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return cast(str | None, payload.get("sub"))
    except JWTError:
        return None


def setup_middleware(app: FastAPI) -> None:
    """Register the Prometheus + JSON access-log middleware on the app."""

    @app.middleware("http")
    async def metrics_and_access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Prometheus counters/histograms + structured JSON access log.

        Auto-increments http_requests_total, observes
        http_request_duration_seconds, tracks active users, and appends one
        JSON line per request to data/logs/app.log with a request id.
        """
        start = time.perf_counter()
        request_id = uuid.uuid4().hex[:12]

        user_id = "-"
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            user_id = _decode_token(auth_header[7:]) or "-"
        bind_request_context(request_id, user_id)

        response = await call_next(request)

        duration = time.perf_counter() - start
        endpoint = metrics.route_template(request)
        metrics.HTTP_REQUESTS_TOTAL.labels(
            method=request.method, endpoint=endpoint, status=str(response.status_code)
        ).inc()
        metrics.HTTP_REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(
            duration
        )
        metrics.record_active(user_id if user_id != "-" else f"ip:{get_remote_address(request)}")

        app_logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"duration_ms": round(duration * 1000, 1)},
        )
        response.headers["X-Request-ID"] = request_id
        return response
