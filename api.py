#!/usr/bin/env python3
"""
FastAPI server for NZ Lotto Powerball wheel analysis.
Reuses existing functions from lotto_wheels.py.

Start with:  uvicorn api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from auth import (
    ALGORITHM,
    SECRET_KEY,
    RefreshRequest,
    Token,
    User,
    UserLogin,
    UserRegister,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_user_record,
    is_account_locked,
    record_failed_login,
    register_user,
    reset_failed_logins,
    verify_refresh_token,
)
from config.settings import Settings as AppSettings
from config_manager import get_settings, validate_startup
from monitoring import health as health_checks
from monitoring import metrics
from monitoring.logging_setup import app_logger, bind_request_context
from security_log import security_logger

# Canonical application configuration (config/settings.py singleton).
_cfg = get_settings()
INTERNAL_NOTIFY_TOKEN = _cfg.INTERNAL_NOTIFY_TOKEN

from lotto_wheels import (
    DIVISIONS,
    WHEELS,
    bandit_recommendation,
    bayesian_posterior,
    block_analysis,
    get_bonus_stats,
    load_draws,
    numerical_attraction,
    positive_negative_split,
    sum_range,
)

# ---------------------------------------------------------------------------
# Rate limiting, caching, and realtime config
# ---------------------------------------------------------------------------

try:
    from settings import settings

    _default_limit = settings.api_rate_limit
    _heavy_limit = settings.heavy_rate_limit
    _ticket_cost = settings.ticket_cost
except ImportError:
    _default_limit = "60/minute"
    _heavy_limit = "5/minute"
    _ticket_cost = 1.50

# Per-user rate limits: authenticated users get the standard limit, anonymous
# callers are throttled harder.
AUTHENTICATED_LIMIT = "60/minute"
ANONYMOUS_LIMIT = "10/minute"

REDIS_URL = _cfg.REDIS_URL or "redis://localhost:6379"
DRAW_EVENT_CHANNEL = "lotto:draw-events"
# Shared secret for the internal new-draw hook comes from config.secrets.

# Cache TTLs
TTL_PREDICTIONS = 300  # 5 minutes
TTL_ANALYTICS = 3600  # 1 hour


def _decode_token(token: str) -> str | None:
    """Decode a JWT and return the username, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def _rate_limit_key(request: Request) -> str:
    """Rate-limit key: 'user:<name>' for valid JWTs, else 'ip:<address>'."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        username = _decode_token(auth_header[7:])
        if username:
            return f"user:{username}"
    return f"ip:{get_remote_address(request)}"


def _redis_client():
    """Return a connected Redis client, or None if Redis is unavailable."""
    try:
        import redis

        client = redis.Redis.from_url(REDIS_URL, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        return None


_redis = _redis_client()
_storage_uri = REDIS_URL if _redis is not None else "memory://"

limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri=_storage_uri,
)


# ---------------------------------------------------------------------------
# Caching (Redis-backed, in-memory fallback via cachetools)
# ---------------------------------------------------------------------------


class ResponseCache:
    """Tiny TTL cache: Redis when available, cachetools otherwise."""

    def __init__(self, redis_client=None):
        self._redis = redis_client
        if self._redis is None:
            from cachetools import TTLCache

            # maxsize caps memory; per-namespace TTLs
            self._local = {
                TTL_PREDICTIONS: TTLCache(maxsize=128, ttl=TTL_PREDICTIONS),
                TTL_ANALYTICS: TTLCache(maxsize=128, ttl=TTL_ANALYTICS),
            }

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def get(self, key: str, ttl: int):
        """Return the cached value for key, or None on miss."""
        try:
            if self._redis is not None:
                raw = self._redis.get(f"apicache:{key}")
                return json.loads(raw) if raw is not None else None
            return self._local[ttl].get(key)
        except Exception:
            return None

    def set(self, key: str, value, ttl: int) -> None:
        """Store value under key with the given TTL (seconds)."""
        try:
            if self._redis is not None:
                self._redis.setex(f"apicache:{key}", ttl, json.dumps(value))
            else:
                self._local[ttl][key] = value
        except Exception:
            pass  # caching must never break a request


cache = ResponseCache(_redis)


def _cache_key(route: str, **params) -> str:
    """Stable cache key for a route + sorted query params."""
    suffix = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{route}?{suffix}"


# ---------------------------------------------------------------------------
# WebSocket connection manager (live draw broadcasts)
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Tracks active /ws/live-draw clients and broadcasts draw events."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> int:
        """Send a JSON message to all clients; drop dead connections.

        Returns the number of clients the message was delivered to.
        """
        delivered = 0
        stale: list[WebSocket] = []
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)
        return delivered


manager = ConnectionManager()


async def broadcast_draw_event(payload: dict) -> int:
    """Broadcast a draw event to all connected WebSocket clients.

    Called in-process; other processes (live_draw_monitor.py,
    update_draws.py) reach this via POST /internal/new-draw or, when Redis
    is available, by publishing to the lotto:draw-events channel.
    """
    return await manager.broadcast(payload)


async def _redis_draw_event_listener() -> None:
    """Relay Redis pub/sub draw events to WebSocket clients (if Redis up)."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.Redis.from_url(REDIS_URL, socket_timeout=2)
        await client.ping()
        pubsub = client.pubsub()
        await pubsub.subscribe(DRAW_EVENT_CHANNEL)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (ValueError, TypeError):
                continue
            await manager.broadcast(payload)
    except Exception:
        return  # Redis bridge is best-effort; HTTP hook still works


# ---------------------------------------------------------------------------
# Lifespan — load draws once at startup, run Redis bridge
# ---------------------------------------------------------------------------

_draws: list | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup()  # fail fast on insecure prod config
    global _draws
    _draws = load_draws()
    listener = asyncio.create_task(_redis_draw_event_listener())
    yield
    listener.cancel()
    _draws = None


# OpenAPI tag groups — every endpoint is assigned to exactly one of these.
TAGS_METADATA = [
    {
        "name": "System",
        "description": "Service liveness and root status endpoints.",
    },
    {
        "name": "Auth",
        "description": "User registration, JWT login, and identity.",
    },
    {
        "name": "Predictions",
        "description": (
            "Number prediction endpoints: frequency, ML, and the dynamic "
            "ensemble fusing Bayesian, Markov, and Albert methods."
        ),
    },
    {
        "name": "Wheels",
        "description": (
            "Lottery wheel listing, abbreviated wheel generation, ticket "
            "checking, and expected-value simulation."
        ),
    },
    {
        "name": "Backtesting",
        "description": (
            "Historical backtests of wheels against past draws, including "
            "bonus-impact analysis and jackpot rollover."
        ),
    },
    {
        "name": "Analytics",
        "description": (
            "Statistical reports: frequency/blocks, bonus statistics, "
            "co-occurrence analysis, Strike checks, and the predictor leaderboard."
        ),
    },
    {
        "name": "Admin",
        "description": "Administrative endpoints (draw ingestion, internal hooks).",
    },
]


app = FastAPI(
    title="Lotto Wheel API",
    version="2.0.0",
    description="Mathematically optimized lottery wheel generation and prediction API",
    contact={"name": "Support", "email": "support@lottowheel.app"},
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)
app.state.limiter = limiter

# CORS — explicit origins only (never "*"). The Vite dev server
# (mobile-frontend) calls the API cross-origin; override with
# CORS_ORIGINS="https://a.com,https://b.com" in production. Wildcards in
# production (DEBUG=false) are rejected by validate_production_secrets().
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_cfg.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers on every response. The CSP is strict by default; the
# Swagger/ReDoc documentation pages get a tailored policy because they
# load their JS/CSS from public CDNs and use inline styles.
_DOCS_PATHS = {"/docs", "/docs/custom", "/redoc", "/docs/oauth2-redirect"}
_CSP_STRICT = "default-src 'self'"
_CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.redoc.ly; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.redoc.ly https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://cdn.jsdelivr.net https://cdn.redoc.ly; "
    "worker-src blob:; "
    "connect-src 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add standard hardening headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        _CSP_DOCS if request.url.path in _DOCS_PATHS else _CSP_STRICT
    )
    return response


@app.middleware("http")
async def metrics_and_access_log(request: Request, call_next):
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
    metrics.HTTP_REQUEST_DURATION.labels(method=request.method, endpoint=endpoint).observe(duration)
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


# Scrape-time health gauges for Prometheus (see monitoring/alerts.yml).
metrics.register_health_collector(_cfg.DB_PATH, REDIS_URL)


# ---------------------------------------------------------------------------
# Custom OpenAPI schema
# ---------------------------------------------------------------------------


def _synthesize_example(model_schema: dict) -> Any:
    """Build a plausible example object from a JSON schema's properties.

    Prefers each property's own example/default, then falls back to a
    type-based placeholder. Returns None when the schema has no usable
    properties (e.g. pure ``$ref`` wrappers).
    """
    props = model_schema.get("properties")
    if not isinstance(props, dict) or not props:
        return None

    def _placeholder(prop: dict) -> Any:
        if "example" in prop:
            return prop["example"]
        if "default" in prop:
            return prop["default"]
        if "enum" in prop:
            return prop["enum"][0]
        items = prop.get("items")
        return {
            "string": "string",
            "integer": 0,
            "number": 0.0,
            "boolean": True,
            "array": [_placeholder(items)] if isinstance(items, dict) else [],
            "object": {},
        }.get(prop.get("type"), "string")

    return {name: _placeholder(prop) for name, prop in props.items()}


def custom_openapi() -> dict[str, Any]:
    """Build (and cache) the enriched OpenAPI schema served at /openapi.json.

    Extends the stock schema with:
      - the v2.0.0 title/description/contact metadata from the FastAPI app
      - an explicit HTTPBearer security scheme (JWT) so Swagger/ReDoc can
        offer bearer-token auth on the protected admin endpoints
      - the tag group descriptions from TAGS_METADATA
      - example values on every component schema: models declaring
        ``json_schema_extra`` keep theirs, the rest get one synthesized
        from their properties via _synthesize_example

    Returns:
        The OpenAPI schema dict (cached on ``app.openapi_schema``).
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        contact=app.contact,
        tags=TAGS_METADATA,
        routes=app.routes,
    )
    # HTTPBearer is declared explicitly so it is present even if no endpoint
    # currently in the schema depends on it; OAuth2PasswordBearer (from
    # auth.py's /me) is added by FastAPI automatically.
    security_schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "HTTPBearer",
        {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
    )
    # Ensure every component schema carries at least one example so Swagger
    # UI / ReDoc render usable sample payloads for all request/response
    # bodies. Models that declare json_schema_extra already have examples;
    # the rest get one synthesized from their declared properties.
    for _name, model_schema in schema.get("components", {}).get("schemas", {}).items():
        if model_schema.get("example") or model_schema.get("examples"):
            continue
        example = _synthesize_example(model_schema)
        if example is not None:
            model_schema["example"] = example
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom 429 response with a Retry-After header."""
    # exc.detail looks like "60 per 1 minute" — derive the window seconds
    retry_after = 60
    detail = str(getattr(exc, "detail", ""))
    if "hour" in detail:
        retry_after = 3600
    elif "second" in detail:
        retry_after = 1
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": f"Rate limit exceeded: {detail}",
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


@app.middleware("http")
async def two_tier_rate_limit(request: Request, call_next):
    """60/min for authenticated users, 10/min for anonymous callers.

    slowapi's default_limits can't express per-request dynamic limits
    (callables there never receive the request), so the two tiers are
    enforced here using the limiter's own storage/strategy — Redis-backed
    when available, in-memory otherwise. The Retry-After value comes from
    the real window reset time.
    """
    from limits import parse as _parse_limit

    if not _cfg.RATE_LIMIT_ENABLED:
        return await call_next(request)

    key = _rate_limit_key(request)
    limit_str = AUTHENTICATED_LIMIT if key.startswith("user:") else ANONYMOUS_LIMIT
    item = _parse_limit(limit_str)
    scope = request.url.path

    if not limiter.limiter.hit(item, key, scope):
        try:
            stats = limiter.limiter.get_window_stats(item, key, scope)
            retry_after = max(1, int(stats.reset - time.time()))
        except Exception:
            retry_after = 60
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "detail": f"Rate limit exceeded: {limit_str}",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Shared input validators
# ---------------------------------------------------------------------------


def _sanitize_string(v: str, max_len: int = 100) -> str:
    """Strip whitespace, cap length, and reject HTML/JS metacharacters."""
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    if len(v) > max_len:
        raise ValueError(f"must be at most {max_len} characters")
    if any(ch in v for ch in ("<", ">", "&", "{", "}")):
        raise ValueError("must not contain HTML/script metacharacters")
    return v


def _unique_sorted_numbers(v: list[int]) -> list[int]:
    """Number lists must be unique and within 1-40; returned sorted."""
    if len(set(v)) != len(v):
        raise ValueError("numbers must be unique")
    if any(n < 1 or n > 40 for n in v):
        raise ValueError("numbers must be between 1 and 40")
    return sorted(v)


def _date_not_future(v: str | None) -> str | None:
    """Dates (YYYY-MM-DD) must be valid and not in the future."""
    if v is None:
        return v
    parsed = datetime.strptime(v, "%Y-%m-%d").date()  # ValueError if malformed
    if parsed > datetime.now().date():
        raise ValueError("date must not be in the future")
    return v


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class CheckRequest(BaseModel):
    """Request body for POST /check (wheel vs draw win check)."""

    wheel: str = Field(description="Wheel name (e.g. double, single1, jackpot7)")
    draw: list[int] = Field(min_length=6, max_length=6, description="6 main draw numbers")
    powerball: int = Field(ge=1, le=10, description="Powerball (1-10)")

    _clean_wheel = field_validator("wheel")(_sanitize_string)

    # draw uniqueness/range are validated in the endpoint (400, not 422)
    # to preserve the documented error contract.

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "wheel": "single1",
                    "draw": [3, 11, 19, 27, 33, 40],
                    "powerball": 5,
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# API v2 models (documented request/response contracts)
# ---------------------------------------------------------------------------


class DrawCreate(BaseModel):
    """Payload for recording a new Lotto draw."""

    draw_number: int = Field(ge=1, description="Official draw number (stored as draw_id)")
    date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Draw date in ISO format (YYYY-MM-DD)",
    )
    main_numbers: list[Annotated[int, Field(ge=1, le=40)]] = Field(
        min_length=6,
        max_length=6,
        description="The six main numbers drawn (1-40)",
    )
    bonus: int = Field(ge=1, le=40, description="Bonus ball (1-40)")

    _numbers_ok = field_validator("main_numbers")(_unique_sorted_numbers)
    _date_ok = field_validator("date")(_date_not_future)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "draw_number": 2350,
                    "date": "2026-08-01",
                    "main_numbers": [3, 11, 19, 27, 33, 40],
                    "bonus": 7,
                }
            ]
        }
    )


class PredictionRequest(BaseModel):
    """Request body for POST /predictions."""

    method: Literal["frequency", "ml", "ensemble"] = Field(
        description=(
            "Prediction method: 'frequency' (counts over the last 30 draws), "
            "'ensemble' (dynamic Bayesian/Markov/Albert fusion), or 'ml' "
            "(trained XGBoost model, requires model.pkl)."
        )
    )
    top_k: int = Field(
        default=20,
        ge=1,
        le=40,
        description="How many top-ranked numbers to return",
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{"method": "ensemble", "top_k": 12}]})


class PredictionResponse(BaseModel):
    """Ranked number prediction with per-number probabilities."""

    numbers: list[int] = Field(description="Top-ranked numbers, best first")
    probabilities: list[float] = Field(
        description="Probability (0-1) for each number, aligned with 'numbers'"
    )
    method_used: str = Field(description="Prediction method that produced this result")
    generated_at: str = Field(description="ISO-8601 timestamp of generation")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "numbers": [7, 13, 22, 28, 35, 3],
                    "probabilities": [0.18, 0.16, 0.15, 0.14, 0.12, 0.11],
                    "method_used": "ensemble",
                    "generated_at": "2026-08-05T14:00:52.397000",
                }
            ]
        }
    )


class WheelRequest(BaseModel):
    """Request body for POST /wheels/generate."""

    pool_size: int = Field(
        ge=6,
        le=20,
        description=(
            "Size of the number pool. Ignored when user_numbers is provided; "
            "otherwise the pool is derived from the hottest numbers of the "
            "last 30 draws."
        ),
    )
    guarantee_type: str = Field(
        default="4 if 4",
        description="Covering guarantee, e.g. '4 if 4', '4 if 5', '5 if 6'",
    )
    user_numbers: list[int] | None = Field(
        default=None,
        description="Optional explicit pool of 6-20 numbers (1-40)",
    )

    _clean_guarantee = field_validator("guarantee_type")(_sanitize_string)

    @field_validator("user_numbers")
    @classmethod
    def _pool_ok(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        return _unique_sorted_numbers(v)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pool_size": 10,
                    "guarantee_type": "4 if 4",
                    "user_numbers": [1, 3, 7, 11, 19, 22, 27, 33, 35, 40],
                }
            ]
        }
    )


class WheelResponse(BaseModel):
    """Generated abbreviated wheel with coverage statistics."""

    tickets: list[list[int]] = Field(description="Generated tickets, each 6 numbers")
    system_used: str = Field(description="Human-readable guarantee description")
    coverage_stats: dict = Field(
        description="Coverage metrics (pair_coverage_pct, ticket_count, ...)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tickets": [[1, 3, 7, 11, 19, 22], [1, 7, 27, 33, 35, 40]],
                    "system_used": "If 4 of your 10 numbers are drawn, you are guaranteed at least one ticket with 4+ matches.",
                    "coverage_stats": {
                        "pair_coverage_pct": 73.33,
                        "ticket_count": 7,
                        "pool_size": 10,
                    },
                }
            ]
        }
    )


class BacktestRequest(BaseModel):
    """Request body for POST /backtest."""

    start_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="First draw date to include (YYYY-MM-DD); None = earliest draw",
    )
    end_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Last draw date to include (YYYY-MM-DD); None = latest draw",
    )
    wheel_type: str = Field(description="Wheel name (e.g. double, single1, jackpot7)")
    ticket_count: int = Field(
        default=10,
        ge=1,
        le=500,
        description=(
            "Number of consecutive draws to evaluate when only one (or no) "
            "date bound is given. Ignored when both start_date and end_date "
            "are set."
        ),
    )

    _clean_wheel = field_validator("wheel_type")(_sanitize_string)
    _start_ok = field_validator("start_date")(_date_not_future)
    _end_ok = field_validator("end_date")(_date_not_future)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "wheel_type": "single1",
                    "ticket_count": 50,
                }
            ]
        }
    )


class BacktestResponse(BaseModel):
    """Aggregated backtest results for a wheel over a draw window."""

    total_draws: int = Field(description="Number of historical draws evaluated")
    total_wins: int = Field(description="Draws in which the wheel won any prize")
    total_prize: float = Field(description="Total prize money won (NZD)")
    roi_pct: float = Field(description="Return on investment in percent")
    division_breakdown: dict = Field(
        description="Win breakdown (div1_wins, winning/losing draws, jackpots)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_draws": 100,
                    "total_wins": 12,
                    "total_prize": 482.50,
                    "roi_pct": -67.8,
                    "division_breakdown": {"div1_wins": 0, "winning_draws": 12, "losing_draws": 88},
                }
            ]
        }
    )


class ErrorResponse(BaseModel):
    """Standard error envelope returned by v2 endpoints."""

    detail: str = Field(description="Human-readable error message")
    error_code: str = Field(description="Machine-readable error code")
    timestamp: str = Field(description="ISO-8601 timestamp of the error")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "detail": "Unknown wheel 'no-such-wheel'.",
                    "error_code": "WHEEL_NOT_FOUND",
                    "timestamp": "2026-08-05T14:00:52.397000",
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Auth dependencies (OpenAPI-visible)
# ---------------------------------------------------------------------------

# HTTPBearer renders a lock icon in Swagger/ReDoc for the admin endpoints that
# depend on it; /me keeps the OAuth2PasswordBearer scheme from auth.py.
http_bearer_scheme = HTTPBearer(auto_error=False)


def require_admin_http(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer_scheme),
) -> User:
    """Require a valid admin JWT presented as an HTTP Bearer token.

    Args:
        credentials: Bearer credentials extracted from the Authorization header.

    Returns:
        The authenticated admin User.

    Raises:
        HTTPException: 401 if the token is missing or invalid,
            403 if the user is not an admin.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide a Bearer token from /token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise JWTError("missing sub")
        if payload.get("type") != "access":
            raise JWTError("not an access token")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    if not payload.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return User(username=username, is_admin=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", tags=["System"])
def root():
    """Root status endpoint.

    Args:
        None.

    Returns:
        dict: Service status and API name.

    Raises:
        Nothing — always succeeds.
    """
    return {"status": "ok", "message": "NZ Lotto Powerball API"}


@app.get("/health", tags=["System"])
def health() -> Response:
    """Full system health check.

    Runs the checks from monitoring.health: database connectivity
    (critical), Redis (non-critical — in-memory fallback exists), disk
    space (warn < 10% free), memory (warn > 90% used), and the age of the
    latest draw in hours (warn > 72h).

    Args:
        None.

    Returns:
        JSONResponse: {"status", "timestamp", "version", "checks",
        "draws"}. Status is "healthy" (all ok), "degraded" (warnings), or
        "unhealthy" (critical failure).

    Raises:
        Nothing — check failures are reported in the payload: HTTP 200
        for healthy/degraded, HTTP 503 when a critical check fails.
    """
    result = health_checks.run_all_checks(_cfg.DB_PATH, REDIS_URL, app.version)
    http_status = result.pop("http_status")
    return JSONResponse(content=result, status_code=http_status)


@app.get("/config", tags=["System"])
def read_config(cfg: AppSettings = Depends(get_settings)):
    """Public, non-secret runtime configuration.

    Args:
        cfg: Injected application Settings singleton.

    Returns:
        dict: app name, debug flag, and API version. Never includes
        secrets or credentials.

    Raises:
        Nothing.
    """
    return {
        "app_name": cfg.APP_NAME,
        "debug": cfg.DEBUG,
        "version": cfg.VERSION,
    }


@app.get("/metrics", include_in_schema=False, tags=["System"])
def prometheus_metrics() -> Response:
    """Prometheus metrics exposition (text format).

    Args:
        None.

    Returns:
        Response: text/plain; version=0.0.4 payload with request
        counters/histograms, business counters, active users, DB query
        durations, and scrape-time health gauges.

    Raises:
        Nothing.
    """
    return Response(content=metrics.render_metrics(), media_type=metrics.CONTENT_TYPE_LATEST)


@app.post("/register", status_code=201, tags=["Auth"])
def register(req: UserRegister):
    """Register a new user.

    Args:
        req: Username and password for the new account.

    Returns:
        dict: Confirmation message.

    Raises:
        HTTPException: 409 if the username already exists.
    """
    ok = register_user(req.username, req.password)
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"message": "User registered successfully"}


@app.post("/token", response_model=Token, tags=["Auth"])
@limiter.limit("5/minute", key_func=get_remote_address)
def login(req: UserLogin, request: Request):
    """Login and receive a JWT access token plus a refresh token.

    Rate limited to 5 attempts per IP per minute. After 5 failed attempts
    the account is locked for 30 minutes (HTTP 423).

    Args:
        req: Username and password credentials.
        request: Incoming request (rate limiting, audit IP).

    Returns:
        Token: JWT access token (15 min) and refresh token (7 days),
        bearer type.

    Raises:
        HTTPException: 401 if the credentials are invalid; 423 if the
            account is locked; 429 when the login rate limit is exceeded.
    """
    ip = get_remote_address(request)

    if is_account_locked(req.username):
        security_logger.warning("login_locked username=%s ip=%s", req.username, ip)
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account locked after too many failed attempts. Try again later.",
        )

    tokens = authenticate_user(req.username, req.password)
    if tokens is None:
        attempts = record_failed_login(req.username)
        security_logger.warning(
            "login_failed username=%s ip=%s attempts=%d",
            req.username,
            ip,
            attempts,
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")

    reset_failed_logins(req.username)
    security_logger.info("login_success username=%s ip=%s", req.username, ip)
    return Token(**tokens)


@app.post("/token/refresh", response_model=Token, tags=["Auth"])
@limiter.limit("5/minute", key_func=get_remote_address)
def refresh_access_token(req: RefreshRequest, request: Request):
    """Exchange a valid refresh token for a new token pair.

    Refresh tokens are rotated: each call issues a new access token
    (15 min) and a new refresh token (7 days). The is_admin claim is
    re-read from the user record so role changes take effect on refresh.

    Args:
        req: The refresh token received from /token.
        request: Incoming request (rate limiting, audit IP).

    Returns:
        Token: Fresh access/refresh token pair.

    Raises:
        HTTPException: 401 if the refresh token is invalid or expired;
            429 when the rate limit is exceeded.
    """
    ip = get_remote_address(request)
    payload = verify_refresh_token(req.refresh_token)
    if payload is None:
        security_logger.warning("refresh_failed ip=%s", ip)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    username = payload["sub"]
    user = get_user_record(username)
    if user is None:
        security_logger.warning("refresh_failed_unknown_user username=%s ip=%s", username, ip)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    security_logger.info("refresh_success username=%s ip=%s", username, ip)
    return Token(
        access_token=create_access_token(username, user["is_admin"]),
        refresh_token=create_refresh_token(username),
    )


@app.get("/me", tags=["Auth"])
def me(user: User | None = Depends(get_current_user)):
    """Return the identity attached to the current bearer token.

    Args:
        user: Decoded JWT user (optional — anonymous callers get None).

    Returns:
        dict: Username/admin flag when authenticated, otherwise
        {"authenticated": False}.

    Raises:
        Nothing — anonymous access is allowed.
    """
    if user:
        return {"username": user.username, "is_admin": user.is_admin, "authenticated": True}
    return {"authenticated": False}


# ---------------------------------------------------------------------------
# WebSocket: live draw broadcast
# ---------------------------------------------------------------------------


async def _heartbeat(websocket: WebSocket) -> None:
    """Send a JSON ping every 30s to keep the connection alive."""
    while True:
        await asyncio.sleep(30)
        await websocket.send_json(
            {
                "type": "ping",
                "ts": datetime.now().isoformat(),
            }
        )


@app.websocket("/ws/live-draw")
async def ws_live_draw(websocket: WebSocket, token: str = ""):
    """Live draw updates over WebSocket.

    Authenticate with a JWT access token in the `token` query param:
        ws://host/ws/live-draw?token=<access_token>

    Clients receive:
      - {"type": "ping", ...} heartbeat every 30 seconds
      - {"type": "new_draw", ...} when a draw is detected, including the
        numbers and any winning-ticket alerts
    """
    username = _decode_token(token)
    if username is None:
        await websocket.close(code=4401)  # unauthorized
        return

    await manager.connect(websocket)
    heartbeat = asyncio.create_task(_heartbeat(websocket))
    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user": username,
                "clients": len(manager.active_connections),
            }
        )
        while True:
            # Keep the socket open; client messages are accepted and ignored
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        manager.disconnect(websocket)


class DrawEvent(BaseModel):
    """Payload for the internal new-draw hook."""

    draw_date: str
    numbers: list[int] = Field(min_length=6, max_length=6)
    bonus: int = Field(ge=1, le=40)
    powerball: int = Field(ge=1, le=10)
    winners: list[dict] = Field(default_factory=list)
    source: str = "internal"

    _numbers_ok = field_validator("numbers")(_unique_sorted_numbers)
    _date_ok = field_validator("draw_date")(_date_not_future)
    _clean_source = field_validator("source")(_sanitize_string)


@app.post("/internal/new-draw", include_in_schema=False, tags=["Admin"])
async def internal_new_draw(
    event: DrawEvent,
    request: Request,
    x_internal_token: str = Header(default=""),
):
    """Hook for live_draw_monitor.py / update_draws.py to announce a draw.

    Protected by the INTERNAL_NOTIFY_TOKEN shared secret (X-Internal-Token
    header). If the secret is not configured, only localhost callers are
    accepted. Broadcasts the event to all /ws/live-draw clients.

    Args:
        event: Draw event payload (date, numbers, bonus, powerball, winners).
        request: Incoming request (used for the localhost fallback check).
        x_internal_token: Shared-secret header value.

    Returns:
        dict: {"broadcast_to": <number of WebSocket clients notified>}.

    Raises:
        HTTPException: 403 if the internal token is wrong or the caller is
            not localhost (when no token is configured).
    """
    if INTERNAL_NOTIFY_TOKEN:
        if x_internal_token != INTERNAL_NOTIFY_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid internal token.")
    elif get_remote_address(request) not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Internal endpoint: localhost only.")

    payload = {
        "type": "new_draw",
        "draw_date": event.draw_date,
        "numbers": sorted(event.numbers),
        "bonus": event.bonus,
        "powerball": event.powerball,
        "winners": event.winners,
        "source": event.source,
        "ts": datetime.now().isoformat(),
    }
    delivered = await broadcast_draw_event(payload)
    return {"broadcast_to": delivered}


@app.get("/wheels", tags=["Wheels"])
def list_wheels() -> dict[str, Any]:
    """Return list of available wheels with metadata.

    Args:
        None.

    Returns:
        dict: {"wheels": {name: {tickets, suggested_powerball, pool_size,
        pool_numbers}}} for every wheel in lotto_wheels.WHEELS.

    Raises:
        Nothing.
    """
    result = {}
    for name, (tickets, pb) in WHEELS.items():
        pool = set()
        for t in tickets:
            pool.update(t)
        result[name] = {
            "name": name,
            "tickets": len(tickets),
            "suggested_powerball": pb,
            "pool_size": len(pool),
            "pool_numbers": sorted(pool),
        }
    return {"wheels": result}


@app.get("/wheel/{wheel_name}", tags=["Wheels"])
def get_wheel(wheel_name: str) -> dict[str, Any]:
    """Return a wheel's tickets and suggested powerball.

    Args:
        wheel_name: Wheel name (e.g. double, single1, jackpot7).

    Returns:
        dict: Tickets (sorted), suggested powerball, ticket count, and cost.

    Raises:
        HTTPException: 404 if the wheel name is unknown.
    """
    if wheel_name not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{wheel_name}'. Available: {list(WHEELS.keys())}",
        )
    tickets, pb = WHEELS[wheel_name]
    return {
        "name": wheel_name,
        "tickets": [sorted(t) for t in tickets],
        "suggested_powerball": pb,
        "ticket_count": len(tickets),
        "cost": len(tickets) * _ticket_cost,
    }


@app.post("/check", tags=["Wheels"])
def check_wheel(req: CheckRequest) -> dict[str, Any]:
    """Check a wheel against a draw and return the win summary.

    Args:
        req: Wheel name, 6 main draw numbers, and the draw's powerball.

    Returns:
        dict: Pool overlap, per-division win counts/prizes, total prize,
        cost, net, and ROI percentage.

    Raises:
        HTTPException: 404 if the wheel name is unknown; 400 if the draw
            numbers are duplicated or outside 1-40.
    """
    if req.wheel not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{req.wheel}'. Available: {list(WHEELS.keys())}",
        )

    if len(set(req.draw)) != 6:
        raise HTTPException(status_code=400, detail="Draw numbers must be unique.")
    if any(n < 1 or n > 40 for n in req.draw):
        raise HTTPException(status_code=400, detail="Main numbers must be between 1 and 40.")

    tickets, wheel_pb = WHEELS[req.wheel]
    draw_set = set(req.draw)
    n_tickets = len(tickets)
    cost = n_tickets * _ticket_cost

    # Score each ticket — highest qualifying division wins
    counts = {d[0]: 0 for d in DIVISIONS}
    for ticket in tickets:
        matches = len(set(ticket) & draw_set)
        pb_hit = wheel_pb == req.powerball
        for label, main_needed, pb_must_match, _ in DIVISIONS:
            if matches == main_needed and pb_hit == pb_must_match:
                counts[label] += 1
                break

    # Pool overlap
    pool_set = set()
    for t in tickets:
        pool_set.update(t)

    divisions = []
    total_prize = 0.0
    for label, _, _, prize in DIVISIONS:
        c = counts[label]
        winnings = c * prize
        if c:
            divisions.append(
                {
                    "division": label,
                    "winners": c,
                    "prize_per_ticket": prize,
                    "total": winnings,
                }
            )
            total_prize += winnings

    net = total_prize - cost
    roi_pct = (net / cost * 100) if cost else 0.0

    return {
        "wheel": req.wheel,
        "draw": sorted(req.draw),
        "powerball": req.powerball,
        "wheel_powerball": wheel_pb,
        "pool_overlap": len(draw_set & pool_set),
        "ticket_count": n_tickets,
        "cost": round(cost, 2),
        "divisions": divisions,
        "total_prize": round(total_prize, 2),
        "net": round(net, 2),
        "roi_pct": round(roi_pct, 2),
    }


@app.get("/check-strike", tags=["Analytics"])
def check_strike(
    n1: int = 0,
    n2: int = 0,
    n3: int = 0,
    n4: int = 0,
) -> dict[str, Any]:
    """Check Lotto Strike against the first 4 numbers of the latest draw.

    Args:
        n1, n2, n3, n4: The four Strike numbers (1-40) in exact order.

    Returns:
        dict: Draw date/numbers, exact match count, Strike division won,
        and estimated prize.

    Raises:
        HTTPException: 400 if any number is missing or outside 1-40;
            503 if draw data is not loaded.
    """
    from prize_calculator import calculate_strike_prize, count_exact_matches

    player_nums = [n1, n2, n3, n4]
    if any(n < 1 or n > 40 for n in player_nums if n != 0):
        raise HTTPException(
            status_code=400,
            detail="Each Strike number must be between 1 and 40.",
        )
    if any(n == 0 for n in player_nums):
        raise HTTPException(
            status_code=400,
            detail="All four Strike numbers (n1, n2, n3, n4) are required.",
        )

    if not _draws:
        raise HTTPException(status_code=503, detail="Draw data not loaded.")

    # Use the latest draw's first 4 numbers
    latest = _draws[-1]
    draw_first4 = list(latest[0][:4])
    draw_date = latest[3]

    exact = count_exact_matches(player_nums, draw_first4)
    result = calculate_strike_prize(exact)

    return {
        "draw_date": draw_date,
        "draw_numbers": draw_first4,
        "player_numbers": player_nums,
        "exact_matches": exact,
        "strike_division": result["division"],
        "division_label": result["division_label"],
        "prize": result["prize"],
        "is_estimated": result["is_estimated"],
    }


@app.get("/stats", tags=["Analytics"])
def get_stats() -> dict[str, Any]:
    """Return statistical report (positive/negative, block analysis, etc.).

    Cached for 1 hour — historical analytics change only when a draw lands.

    Args:
        None.

    Returns:
        dict: Positive/negative numbers, frequency table, block analysis,
        sum range, numerical attraction, Bayesian top-10, bandit top-6,
        plus a "cache" key describing the cache state.

    Raises:
        HTTPException: 503 if draw data is not loaded.
    """
    if not _draws:
        raise HTTPException(status_code=503, detail="Draw data not loaded.")

    key = _cache_key("/stats")
    cached = cache.get(key, TTL_ANALYTICS)
    if cached is not None:
        cached["cache"] = {"hit": True, "ttl": TTL_ANALYTICS, "backend": cache.backend}
        return cached

    draws = _draws
    pos, neg, freq = positive_negative_split(draws)
    blocks = block_analysis(draws)
    low_sum, high_sum = sum_range(draws)
    adj_ratio = numerical_attraction(draws)
    bayes = bayesian_posterior(draws)
    top_bayes = [n for n, _ in sorted(bayes.items(), key=lambda x: x[1], reverse=True)[:10]]
    bandit_top = bandit_recommendation(draws)

    result = {
        "positive_numbers": sorted(pos),
        "negative_numbers": sorted(neg),
        "frequency": dict(freq.most_common()),
        "block_analysis": {f"pos_{i+1}": cats for i, cats in blocks.items()},
        "sum_range": {"low": low_sum, "high": high_sum},
        "numerical_attraction_pct": round(adj_ratio * 100, 1),
        "bayesian_top_10": top_bayes,
        "bandit_top_6": bandit_top,
    }
    cache.set(key, result, TTL_ANALYTICS)
    result["cache"] = {"hit": False, "ttl": TTL_ANALYTICS, "backend": cache.backend}
    return result


@app.get("/api/bonus/stats", tags=["Analytics"])
def get_bonus_stats_endpoint() -> list[dict]:
    """Return bonus ball statistics for numbers 1-40.

    Args:
        None.

    Returns:
        list[dict]: Per-number bonus statistics from lotto_wheels
        (counts, gaps, recency).

    Raises:
        Nothing — an empty list is returned when no data exists.
    """
    conn = sqlite3.connect("lotto.db")
    try:
        return get_bonus_stats(conn)
    finally:
        conn.close()


@app.get("/predict/bonus_bayesian", tags=["Predictions"])
def predict_bonus_bayesian(k: int = 5) -> list[dict]:
    """Return top-k bonus ball predictions using Dirichlet-Multinomial Bayesian.

    Args:
        k: Number of top predictions to return (default 5, capped at 40).

    Returns:
        list[dict]: Ranked entries with bonus_number and probability.

    Raises:
        HTTPException: 404 if no bonus ball data exists.
    """
    from predictions import BonusBayesian

    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute("SELECT bonus FROM draws ORDER BY draw_date ASC").fetchall()
    finally:
        conn.close()

    bonus_balls = [r[0] for r in rows if r[0] and 1 <= r[0] <= 40]
    if not bonus_balls:
        raise HTTPException(status_code=404, detail="No bonus ball data found.")

    model = BonusBayesian(bonus_balls, alpha=1.0)
    top_k = model.predict_top_k(k=min(k, 40))
    return [
        {"rank": i + 1, "bonus_number": n, "probability": round(p, 6)}
        for i, (n, p) in enumerate(top_k)
    ]


@app.get("/predict/bonus_gap", tags=["Predictions"])
def predict_bonus_gap(k: int = 5) -> list[dict]:
    """Return top-k 'due' bonus ball predictions using gap + frequency scoring.

    Args:
        k: Number of top predictions to return (default 5, capped at 40).

    Returns:
        list[dict]: Ranked entries with bonus_number and gap score.

    Raises:
        Nothing — an empty list is returned when no data exists.
    """
    from predictions import bonus_gap_prediction

    conn = sqlite3.connect("lotto.db")
    try:
        top_k = bonus_gap_prediction(conn, k=min(k, 40))
        return [{"rank": i + 1, "bonus_number": n, "score": s} for i, (n, s) in enumerate(top_k)]
    finally:
        conn.close()


@app.get("/predict/bonus/hierarchical", tags=["Predictions"])
def predict_bonus_hierarchical(k: int = 5, halflife: int = 90) -> list[dict]:
    """Return top-k bonus predictions using Hierarchical Bayesian with recency.

    Args:
        k: Number of top predictions (default 5, capped at 40).
        halflife: Recency half-life in days (default 90).

    Returns:
        list[dict]: Ranked entries with bonus_number, posterior_mean, and
        posterior_std.

    Raises:
        HTTPException: 404 if no bonus ball data exists.
    """
    from predictions import HierarchicalBonusPredictor

    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute("SELECT draw_date, bonus FROM draws ORDER BY draw_date ASC").fetchall()
    finally:
        conn.close()

    draws = [(r[0], r[1]) for r in rows if r[1] and 1 <= r[1] <= 40]
    if not draws:
        raise HTTPException(status_code=404, detail="No bonus ball data found.")

    model = HierarchicalBonusPredictor(draws, recency_halflife_days=halflife)
    model.fit()
    top_k = model.predict_top_k(k=min(k, 40))
    return [
        {"rank": i + 1, "bonus_number": n, "posterior_mean": m, "posterior_std": s}
        for i, (n, m, s) in enumerate(top_k)
    ]


@app.get("/predict/bonus/probability", tags=["Predictions"])
def predict_bonus_probability(num: int, halflife: int = 90) -> dict[str, Any]:
    """Return posterior probability for a specific bonus number.

    Args:
        num: Bonus ball number (1-40).
        halflife: Recency half-life in days (default 90).

    Returns:
        dict: Posterior mean/std for the requested bonus number and the
        halflife used.

    Raises:
        HTTPException: 400 if num is outside 1-40; 404 if no bonus data
            exists.
    """
    if not (1 <= num <= 40):
        raise HTTPException(status_code=400, detail="num must be 1-40.")

    from predictions import HierarchicalBonusPredictor

    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute("SELECT draw_date, bonus FROM draws ORDER BY draw_date ASC").fetchall()
    finally:
        conn.close()

    draws = [(r[0], r[1]) for r in rows if r[1] and 1 <= r[1] <= 40]
    if not draws:
        raise HTTPException(status_code=404, detail="No bonus ball data found.")

    model = HierarchicalBonusPredictor(draws, recency_halflife_days=halflife)
    model.fit()
    prob = model.probability_of_number(num)
    return {
        "bonus_number": num,
        "posterior_mean": prob,
        "posterior_std": round(model.posterior_std.get(num, 0), 6),
        "halflife_days": halflife,
    }


@app.get("/predict/ensemble", tags=["Predictions"])
def predict_ensemble(main: int = 15, bonus: int = 5, pb: int = 3) -> dict[str, Any]:
    """Return ensemble predictions fusing Bayesian, Markov, and Albert methods.

    Responses are cached for 5 minutes (Redis when available, in-memory
    otherwise) since the underlying walk-forward fit is expensive.

    Args:
        main: Number of top main numbers (default 15).
        bonus: Number of top bonus balls (default 5).
        pb: Number of top Powerballs (default 3).

    Returns:
        dict: Ranked main/bonus/powerball lists with ensemble weights,
        plus a "cache" key describing the cache state.

    Raises:
        HTTPException: propagated from the predictor layer when draw data
            is unavailable.
    """
    key = _cache_key("/predict/ensemble", main=main, bonus=bonus, pb=pb)
    cached = cache.get(key, TTL_PREDICTIONS)
    if cached is not None:
        cached["cache"] = {"hit": True, "ttl": TTL_PREDICTIONS, "backend": cache.backend}
        return cached

    conn = sqlite3.connect("lotto.db")
    try:
        from ensemble import EnsemblePredictor

        ep = EnsemblePredictor(conn)
        ep.fit_weights(validation_draws=10)
        result = ep.predict_all(main_top=main, bonus_top=bonus, pb_top=pb)
    finally:
        conn.close()

    cache.set(key, result, TTL_PREDICTIONS)
    result["cache"] = {"hit": False, "ttl": TTL_PREDICTIONS, "backend": cache.backend}
    return result


# ---------------------------------------------------------------------------
# EV Simulation
# ---------------------------------------------------------------------------


class EVSimulationRequest(BaseModel):
    """Request body for POST /ev_simulation (Monte Carlo EV simulation)."""

    wheel: str = Field(description="Wheel name (e.g. double, single1, jackpot7)")
    num_sims: int = Field(
        default=100_000,
        ge=10_000,
        le=5_000_000,
        description="Number of Monte Carlo simulations (10 000 – 5 000 000)",
    )

    _clean_wheel = field_validator("wheel")(_sanitize_string)

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"wheel": "single1", "num_sims": 100000}]}
    )


@app.post("/ev_simulation", tags=["Wheels"])
@limiter.limit(_heavy_limit)
def ev_simulation_endpoint(req: EVSimulationRequest, request: Request = None) -> dict[str, Any]:
    """Run a Monte Carlo bonus-ball EV simulation for a wheel.

    Args:
        req: Wheel name and number of simulations (10 000 – 5 000 000).
            Body example: {"wheel": "single1", "num_sims": 100000}

    Returns:
        dict: Expected value with/without the bonus ball, premium percent,
        and upgrade count (see backtest.simulate_bonus_ev).

    Raises:
        HTTPException: 404 if the wheel name is unknown; 400 if num_sims
            is outside the allowed range; 429 when the heavy rate limit is
            exceeded.
    """
    if req.wheel not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{req.wheel}'. Available: {list(WHEELS.keys())}",
        )
    if not (10_000 <= req.num_sims <= 5_000_000):
        raise HTTPException(status_code=400, detail="num_sims must be 10 000 – 5 000 000.")

    from backtest import simulate_bonus_ev

    return simulate_bonus_ev(req.wheel, num_sims=req.num_sims)


# ---------------------------------------------------------------------------
# Bonus–Main Co-occurrence
# ---------------------------------------------------------------------------


@app.get("/analysis/cooccurrence/matrix", tags=["Analytics"])
def cooccurrence_matrix_endpoint(min_support: int = 5) -> dict[str, Any]:
    """Return the bonus–main co-occurrence matrix as a nested JSON structure.

    Args:
        min_support: Minimum count threshold for including a pair
            (default 5).

    Returns:
        dict: {"index": bonus numbers, "columns": main numbers,
        "data": count matrix}.

    Raises:
        Nothing — empty structures are returned when no pairs qualify.
    """
    conn = sqlite3.connect("lotto.db")
    try:
        from analysis_bonus_pairs import compute_cooccurrence_matrix

        df = compute_cooccurrence_matrix(conn, min_support=min_support)
        return {
            "index": df.index.tolist(),
            "columns": df.columns.tolist(),
            "data": df.values.tolist(),
        }
    finally:
        conn.close()


@app.get("/analysis/cooccurrence/pairs/{bonus_num}", tags=["Analytics"])
def cooccurrence_pairs_endpoint(bonus_num: int, top_k: int = 3) -> list[dict]:
    """Return top-k main numbers that co-occur with a specific bonus ball.

    Args:
        bonus_num: Bonus ball number (1-40).
        top_k: Number of main numbers to return (default 3).

    Returns:
        list[dict]: Entries with main_number and co-occurrence count.

    Raises:
        HTTPException: 400 if bonus_num is outside 1-40.
    """
    if not (1 <= bonus_num <= 40):
        raise HTTPException(status_code=400, detail="bonus_num must be 1-40.")

    conn = sqlite3.connect("lotto.db")
    try:
        from analysis_bonus_pairs import get_top_pairs_for_bonus

        pairs = get_top_pairs_for_bonus(conn, bonus_num, top_k=top_k)
        return [{"main_number": n, "count": c} for n, c in pairs]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Backtest Bonus Impact
# ---------------------------------------------------------------------------


@app.get("/backtest/bonus_impact", tags=["Backtesting"])
@limiter.limit(_heavy_limit)
def backtest_bonus_impact_endpoint(
    wheel_name: str, draws: int = 0, request: Request = None
) -> dict[str, Any]:
    """Return bonus-impact report for a wheel against historical draws.

    Cached for 1 hour — backtests over historical data are deterministic
    until a new draw lands.

    Args:
        wheel_name: Wheel name (e.g. 'single1', 'double').
        draws: Number of recent draws to test (0 = all).
        request: Incoming request (rate limiting).

    Returns:
        dict: Bonus premium percent, upgraded tickets, value added, and
        upgrade breakdown, plus a "cache" key describing the cache state.

    Raises:
        HTTPException: 404 if the wheel name is unknown; 429 when the
            heavy rate limit is exceeded.
    """
    if wheel_name not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{wheel_name}'. Available: {list(WHEELS.keys())}",
        )

    key = _cache_key("/backtest/bonus_impact", wheel_name=wheel_name, draws=draws)
    cached = cache.get(key, TTL_ANALYTICS)
    if cached is not None:
        cached["cache"] = {"hit": True, "ttl": TTL_ANALYTICS, "backend": cache.backend}
        return cached

    from backtest import backtest_bonus_impact

    num = draws if draws > 0 else None
    result = backtest_bonus_impact(wheel_name, num)
    cache.set(key, result, TTL_ANALYTICS)
    result["cache"] = {"hit": False, "ttl": TTL_ANALYTICS, "backend": cache.backend}
    return result


@app.get("/analysis/cooccurrence/triplets", tags=["Analytics"])
def cooccurrence_triplets_endpoint(top_n: int = 10) -> list[dict]:
    """Return top-N bonus+main+main triplets.

    Args:
        top_n: Number of triplets to return (default 10).

    Returns:
        list[dict]: Entries with bonus, main1, main2, and count.

    Raises:
        Nothing — an empty list is returned when no triplets qualify.
    """
    conn = sqlite3.connect("lotto.db")
    try:
        from analysis_bonus_pairs import get_top_triplets

        triplets = get_top_triplets(conn, top_n=top_n)
        return [{"bonus": b, "main1": m1, "main2": m2, "count": c} for b, m1, m2, c in triplets]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Predictor Leaderboard
# ---------------------------------------------------------------------------


@app.get("/leaderboard", tags=["Analytics"])
def leaderboard() -> dict[str, Any]:
    """Predictor leaderboard built from accuracy_tracker scorecards.

    Returns predictors ranked by hit rate (desc), then Brier score (asc).
    Empty when no predictor has been evaluated yet.

    Args:
        None.

    Returns:
        dict: {"leaderboard": [ranked predictor entries with hit rate,
        Brier score, top-k accuracies, and MRR]}.

    Raises:
        Nothing — an empty leaderboard is returned when the scorecards
        table does not exist yet.
    """
    conn = sqlite3.connect("lotto.db")
    try:
        rows = conn.execute(
            "SELECT predictor_name, window_size, draws_evaluated, brier_score, "
            "hit_rate, top10_accuracy, top15_accuracy, top20_accuracy, "
            "mean_reciprocal_rank, last_updated "
            "FROM scorecards"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []  # scorecards table not created yet
    finally:
        conn.close()

    entries = [
        {
            "predictor_name": r[0],
            "window_size": r[1],
            "draws_evaluated": r[2],
            "brier_score": r[3],
            "hit_rate": r[4],
            "top10_accuracy": r[5],
            "top15_accuracy": r[6],
            "top20_accuracy": r[7],
            "mean_reciprocal_rank": r[8],
            "last_updated": r[9],
        }
        for r in rows
    ]
    entries.sort(key=lambda e: (-(e["hit_rate"] or 0.0), e["brier_score"] or 999.0))
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank
    return {"leaderboard": entries}


# ---------------------------------------------------------------------------
# v2 endpoints: draws admin, unified predictions, wheel generation, backtest
# ---------------------------------------------------------------------------


def _frequency_probs(last_n: int = 30) -> dict[int, float]:
    """Frequency probabilities (0-1) for numbers 1-40 over recent draws.

    Args:
        last_n: How many recent draws to count (default 30).

    Returns:
        dict mapping number (1-40) to its appearance frequency as a
        fraction of draws; empty dict when no draw data exists.
    """
    conn = sqlite3.connect("lotto.db")
    try:
        with metrics.Timer("frequency_probs"):
            rows = conn.execute(
                "SELECT numbers FROM draws ORDER BY draw_date DESC LIMIT ?",
                (last_n,),
            ).fetchall()
    finally:
        conn.close()

    from collections import Counter

    freq: Counter = Counter()
    n_draws = 0
    for (nums_str,) in rows:
        try:
            nums = [int(x.strip()) for x in nums_str.split(",")]
        except (ValueError, AttributeError):
            continue
        if len(nums) == 6:
            freq.update(nums)
            n_draws += 1
    if n_draws == 0:
        return {}
    return {n: freq.get(n, 0) / n_draws for n in range(1, 41)}


@app.post(
    "/draws",
    status_code=201,
    tags=["Admin"],
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
        403: {"model": ErrorResponse, "description": "Admin privileges required."},
        409: {"model": ErrorResponse, "description": "A draw already exists for this date."},
        422: {"model": ErrorResponse, "description": "Payload validation failed."},
    },
)
def create_draw(draw: DrawCreate, admin: User = Depends(require_admin_http)):
    """Record a new Lotto draw (admin only).

    Maps DrawCreate onto the draws table: draw_number -> draw_id,
    date -> draw_date, main_numbers -> comma-separated numbers string.
    DrawCreate carries no powerball field, so powerball is stored as 0
    (neutral sentinel: never matches a wheel powerball, excluded from
    powerball frequency counts).

    Args:
        draw: Draw payload (draw number, date, 6 main numbers, bonus).
        admin: Authenticated admin user (HTTP Bearer JWT).

    Returns:
        dict: Confirmation with draw_id and draw_date.

    Raises:
        HTTPException: 401 if the bearer token is missing/invalid; 403 if
            the user is not an admin; 409 if a draw already exists for the
            given date (or the draw_id primary key is taken).
    """
    conn = sqlite3.connect("lotto.db")
    try:
        from update_draws import draw_exists, init_db

        init_db(conn)
        if draw_exists(conn, draw.date):
            raise HTTPException(
                status_code=409,
                detail=f"A draw already exists for date {draw.date}.",
            )
        nums_str = ",".join(str(n) for n in draw.main_numbers)
        try:
            conn.execute(
                "INSERT INTO draws (draw_id, draw_date, numbers, bonus, powerball) "
                "VALUES (?, ?, ?, ?, 0)",
                (draw.draw_number, draw.date, nums_str, draw.bonus),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Draw could not be inserted (duplicate?): {exc}",
            ) from exc
    finally:
        conn.close()

    # Refresh the in-memory draw cache so analytics see the new draw.
    global _draws
    _draws = load_draws()

    security_logger.info(
        "admin_draw_created user=%s draw_id=%s draw_date=%s",
        admin.username,
        draw.draw_number,
        draw.date,
    )

    return {
        "message": "Draw recorded successfully",
        "draw_id": draw.draw_number,
        "draw_date": draw.date,
    }


@app.post(
    "/predictions",
    response_model=PredictionResponse,
    tags=["Predictions"],
    responses={
        404: {"model": ErrorResponse, "description": "No draw data available."},
        422: {"model": ErrorResponse, "description": "Payload validation failed."},
        501: {"model": ErrorResponse, "description": "ML model not available."},
    },
)
def create_prediction(req: PredictionRequest) -> PredictionResponse:
    """Generate top-k number predictions with the requested method.

    Methods:
      - frequency: appearance counts over the last 30 draws.
      - ensemble: dynamic Bayesian/Markov/Albert fusion (same internals as
        GET /predict/ensemble).
      - ml: trained XGBoost model from predict_ml.py (requires model.pkl;
        run train_ml_model.py first).

    Args:
        req: Prediction method and top_k (1-40, default 20).

    Returns:
        PredictionResponse: Ranked numbers with probabilities normalized
        to 0-1, the method used, and a generation timestamp.

    Raises:
        HTTPException: 404 if no draw data exists; 501 if the ML method is
            requested but no trained model (model.pkl) is available.
    """
    generated_at = datetime.now().isoformat()

    if req.method == "frequency":
        probs = _frequency_probs(last_n=30)
        if not probs:
            raise HTTPException(status_code=404, detail="No draw data found.")
        ranked = sorted(probs.items(), key=lambda x: x[1], reverse=True)[: req.top_k]
        numbers = [n for n, _ in ranked]
        probabilities = [round(p, 6) for _, p in ranked]
        metrics.PREDICTIONS_GENERATED.labels(method="frequency").inc()
        return PredictionResponse(
            numbers=numbers,
            probabilities=probabilities,
            method_used="frequency",
            generated_at=generated_at,
        )

    if req.method == "ensemble":
        conn = sqlite3.connect("lotto.db")
        try:
            from ensemble import EnsemblePredictor

            ep = EnsemblePredictor(conn)
            if not ep.draws:
                raise HTTPException(status_code=404, detail="No draw data found.")
            ep.fit_weights(validation_draws=10)
            ranked = ep.predict_main_numbers(top_n=req.top_k)
        finally:
            conn.close()
        # Ensemble probabilities are weighted averages of sub-predictor
        # probabilities — already normalized to 0-1.
        metrics.PREDICTIONS_GENERATED.labels(method="ensemble").inc()
        return PredictionResponse(
            numbers=[n for n, _ in ranked],
            probabilities=[round(p, 6) for _, p in ranked],
            method_used="ensemble",
            generated_at=generated_at,
        )

    # method == "ml"
    if not os.path.exists("model.pkl"):
        raise HTTPException(
            status_code=501,
            detail=(
                "ML predictions require a trained model (model.pkl). "
                "Run train_ml_model.py first, or use method='frequency' "
                "or 'ensemble'."
            ),
        )
    import pickle

    with open("model.pkl", "rb") as fh:
        model_data = pickle.load(fh)
    from predict_ml import load_draws as ml_load_draws
    from predict_ml import predict as ml_predict

    draws = ml_load_draws("lotto.db")
    if not draws:
        raise HTTPException(status_code=404, detail="No draw data found.")
    pred = ml_predict(draws, model_data, top_n=req.top_k)
    top_probs = pred.get("top_probs", {})
    numbers = pred.get("numbers", [])
    metrics.PREDICTIONS_GENERATED.labels(method="ml").inc()
    return PredictionResponse(
        numbers=numbers,
        probabilities=[round(float(top_probs.get(n, 0.0)), 6) for n in numbers],
        method_used="ml",
        generated_at=generated_at,
    )


@app.post(
    "/wheels/generate",
    response_model=WheelResponse,
    tags=["Wheels"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid pool size or guarantee type."},
        404: {"model": ErrorResponse, "description": "No wheel system found for parameters."},
        422: {"model": ErrorResponse, "description": "Payload validation failed."},
    },
)
def generate_wheel(
    req: WheelRequest,
    user: User | None = Depends(get_current_user),
) -> WheelResponse:
    """Generate a lottery wheel using the specified guarantee system.

    Wraps wheel_generator.generate_abbreviated_wheel. When user_numbers is
    omitted, the pool is derived from the pool_size hottest numbers of the
    last 30 draws (falling back to 1..pool_size when no data exists).

    Args:
        req: Pool size (6-20), covering guarantee (e.g. '4 if 4'), and an
            optional explicit pool of numbers.
        user: Optional authenticated user (for the audit log).

    Returns:
        WheelResponse with generated tickets and coverage statistics
        (pair_coverage_pct = fraction of C(pool,2) pairs covered by at
        least one ticket, ticket_count, pool_size).

    Raises:
        HTTPException: 400 on invalid pool size or guarantee type (bad
            guarantee strings, out-of-range or duplicate pool numbers);
            404 when no wheel system is found for the requested
            guarantee/pool combination.
    """
    if req.user_numbers:
        if len(req.user_numbers) < 6 or len(req.user_numbers) > 20:
            raise HTTPException(
                status_code=400,
                detail="user_numbers must contain between 6 and 20 numbers.",
            )
        if len(set(req.user_numbers)) != len(req.user_numbers):
            raise HTTPException(status_code=400, detail="user_numbers must be unique.")
        if any(n < 1 or n > 40 for n in req.user_numbers):
            raise HTTPException(status_code=400, detail="user_numbers must be between 1 and 40.")
        pool = sorted(set(req.user_numbers))
    else:
        freq = _frequency_probs(last_n=30)
        if freq:
            ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
            pool = sorted(n for n, _ in ranked[: req.pool_size])
        else:
            pool = list(range(1, req.pool_size + 1))

    from wheel_generator import generate_abbreviated_wheel

    try:
        tickets, desc = generate_abbreviated_wheel(pool, guarantee=req.guarantee_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not tickets:
        raise HTTPException(
            status_code=404,
            detail=f"No wheel system found for parameters: {desc}",
        )

    covered_pairs: set[tuple[int, int]] = set()
    for ticket in tickets:
        covered_pairs.update(itertools.combinations(sorted(set(ticket)), 2))
    total_pairs = math.comb(len(pool), 2)
    pair_coverage_pct = round(len(covered_pairs) / total_pairs * 100, 2) if total_pairs else 0.0

    metrics.WHEELS_GENERATED.labels(system_type=req.guarantee_type).inc()
    security_logger.info(
        "wheel_generated user=%s pool_size=%d guarantee=%s tickets=%d",
        user.username if user else "anonymous",
        len(pool),
        req.guarantee_type,
        len(tickets),
    )

    return WheelResponse(
        tickets=[sorted(t) for t in tickets],
        system_used=desc,
        coverage_stats={
            "pair_coverage_pct": pair_coverage_pct,
            "ticket_count": len(tickets),
            "pool_size": len(pool),
            "guarantee": req.guarantee_type,
        },
    )


@app.post(
    "/backtest",
    response_model=BacktestResponse,
    tags=["Backtesting"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid date range."},
        404: {"model": ErrorResponse, "description": "Unknown wheel or no draws in range."},
        422: {"model": ErrorResponse, "description": "Payload validation failed."},
    },
)
def run_backtest(
    req: BacktestRequest,
    user: User | None = Depends(get_current_user),
) -> BacktestResponse:
    """Backtest a wheel against a window of historical draws.

    Reuses backtest.run_multi_draw_backtest (jackpot rollover + pool
    allocation). The draw window is mapped from start_date/end_date via
    load_draws dates:

      - both dates set: every draw in [start_date, end_date]
      - only start_date: ticket_count draws from the first draw on/after it
      - only end_date: ticket_count draws up to the last draw on/before it
      - neither: all draws

    Args:
        req: Optional date bounds, wheel name, and ticket_count (draw
            window size for open-ended ranges, 1-500, default 10).
        user: Optional authenticated user (for the audit log).

    Returns:
        BacktestResponse: Draws evaluated, winning draws, total prize,
        ROI percent, and a division/jackpot breakdown.

    Raises:
        HTTPException: 404 if the wheel is unknown or no draws fall in the
            window; 400 if start_date is after end_date.
    """
    if req.wheel_type not in WHEELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wheel '{req.wheel_type}'. Available: {list(WHEELS.keys())}",
        )
    if req.start_date and req.end_date and req.start_date > req.end_date:
        raise HTTPException(status_code=400, detail="start_date must not be after end_date.")

    all_draws = load_draws()
    if not all_draws:
        raise HTTPException(status_code=404, detail="No draw data found.")

    total = len(all_draws)
    dates = [str(d[3]) for d in all_draws]

    if req.start_date and req.end_date:
        idxs = [i for i, d in enumerate(dates) if req.start_date <= d <= req.end_date]
        if not idxs:
            raise HTTPException(status_code=404, detail="No draws in the specified date range.")
        start_idx, n_draws = idxs[0], len(idxs)
    elif req.start_date:
        start_idx = next((i for i, d in enumerate(dates) if d >= req.start_date), None)
        if start_idx is None:
            raise HTTPException(status_code=404, detail="No draws on or after start_date.")
        n_draws = min(req.ticket_count, total - start_idx)
    elif req.end_date:
        end_idx = next(
            (i for i in range(total - 1, -1, -1) if dates[i] <= req.end_date),
            None,
        )
        if end_idx is None:
            raise HTTPException(status_code=404, detail="No draws on or before end_date.")
        n_draws = min(req.ticket_count, end_idx + 1)
        start_idx = end_idx - n_draws + 1
    else:
        start_idx, n_draws = 0, total

    from backtest import run_multi_draw_backtest

    result = run_multi_draw_backtest(req.wheel_type, start_draw_id=start_idx, num_draws=n_draws)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    records = result["draw_records"]
    total_wins = sum(1 for r in records if r["draw_prize"] > 0)

    security_logger.info(
        "backtest_run user=%s wheel=%s start=%s end=%s draws=%d",
        user.username if user else "anonymous",
        req.wheel_type,
        req.start_date,
        req.end_date,
        result["num_draws"],
    )

    return BacktestResponse(
        total_draws=result["num_draws"],
        total_wins=total_wins,
        total_prize=result["total_prize"],
        roi_pct=result["roi_pct"],
        division_breakdown={
            "div1_wins": sum(r["div1_winners"] for r in records),
            "winning_draws": total_wins,
            "losing_draws": len(records) - total_wins,
            "jackpot_occurrences": result["jackpot_occurrences"],
            "forced_distributions": result["forced_distributions"],
        },
    )


# ---------------------------------------------------------------------------
# Custom documentation: ReDoc with a dark theme
# ---------------------------------------------------------------------------

_REDOC_DARK_HTML = """<!DOCTYPE html>
<html>
  <head>
    <title>Lotto Wheel API — ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      body { margin: 0; padding: 0; background: #0a0a0a; color: #e5e5e5; }
      /* Dark neutral palette matching the dashboard (#0a0a0a/#171717) */
      redoc .menu-content,
      redoc [class*="scrollbar-container"] { background: #0a0a0a !important; }
      redoc, redoc * { scrollbar-color: #404040 #0a0a0a; }
      #redoc-container { background: #0a0a0a; }
    </style>
  </head>
  <body>
    <div id="redoc-container"></div>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
    <script>
      Redoc.init("/openapi.json", {
        theme: {
          colors: {
            primary: { main: "#38bdf8" },
            success: { main: "#4ade80" },
            warning: { main: "#facc15" },
            error: { main: "#f87171" },
            text: { primary: "#e5e5e5", secondary: "#a3a3a3" },
            border: { dark: "#262626", light: "#404040" },
            responses: {
              success: { color: "#4ade80", backgroundColor: "#052e16" },
              error: { color: "#f87171", backgroundColor: "#450a0a" },
              redirect: { color: "#facc15", backgroundColor: "#422006" },
              info: { color: "#38bdf8", backgroundColor: "#082f49" }
            },
            http: {
              get: "#38bdf8",
              post: "#4ade80",
              put: "#facc15",
              delete: "#f87171"
            }
          },
          typography: {
            fontSize: "15px",
            headings: { fontFamily: "system-ui, sans-serif" },
            code: { backgroundColor: "#171717", color: "#e5e5e5" }
          },
          rightPanel: { backgroundColor: "#171717", textColor: "#e5e5e5" },
          sidebar: { backgroundColor: "#0a0a0a", textColor: "#d4d4d4" },
          fab: { backgroundColor: "#262626" }
        },
        hideDownloadButton: false
      }, document.getElementById("redoc-container"));
    </script>
  </body>
</html>
"""


@app.get("/docs/custom", include_in_schema=False, tags=["System"])
def custom_docs() -> HTMLResponse:
    """ReDoc API documentation with a dark dashboard-matching theme.

    Args:
        None.

    Returns:
        HTMLResponse: Self-contained page loading ReDoc from the
        redoc.ly CDN, pointed at /openapi.json, styled with the
        #0a0a0a/#171717 neutral palette.

    Raises:
        Nothing.
    """
    return HTMLResponse(content=_REDOC_DARK_HTML)


# ---------------------------------------------------------------------------
# Mobile frontend static hosting
# ---------------------------------------------------------------------------

# Serve the built React app (mobile-frontend/dist) at /mobile when present.
_mobile_dist = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mobile-frontend", "dist")
if os.path.isdir(_mobile_dist):
    from fastapi.staticfiles import StaticFiles

    app.mount("/mobile", StaticFiles(directory=_mobile_dist, html=True), name="mobile")
