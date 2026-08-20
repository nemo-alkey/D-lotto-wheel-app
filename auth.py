#!/usr/bin/env python3
"""
auth.py — JWT authentication and user management for the NZ Lotto API.

Provides:
  - User registration with bcrypt password hashing and complexity rules
    (min 8 chars, 1 uppercase, 1 lowercase, 1 digit)
  - JWT access tokens (15 min) + refresh tokens (7 days), typed via a
    "type" claim so refresh tokens cannot be used as access tokens
  - Account lockout after 5 failed login attempts (30 min cooldown)
  - Token decoding dependency (get_current_user)
  - User storage in lotto.db (users table)
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, field_validator

from config.settings import settings as _app_settings

SECRET_KEY = _app_settings.SECRET_KEY

try:
    from settings import settings

    ALGORITHM = settings.jwt_algorithm
    ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_expire_minutes
    REFRESH_TOKEN_EXPIRE_DAYS = settings.jwt_refresh_expire_days
    DB_PATH = settings.db_path
except ImportError:
    # Fallback for environments without settings.py
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "15"))
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto.db")

# bcrypt's 72-byte input limit; longer passwords are truncated explicitly
# (passlib 1.7.4 is incompatible with bcrypt>=5, so hash/verify are done
# directly with bcrypt — the $2b$ hash format is identical, so existing
# passlib-generated hashes in the users table still verify).
_BCRYPT_MAX_BYTES = 72

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token", auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_PASSWORD_BYTES = 128


def _clean_username(v: str) -> str:
    """Strip whitespace and enforce a safe username charset/length."""
    v = v.strip()
    if not 3 <= len(v) <= 50:
        raise ValueError("username must be 3-50 characters")
    if not _USERNAME_RE.match(v):
        raise ValueError("username may only contain letters, digits, '_', '.', '-'")
    return v


def _check_password_complexity(password: str) -> str:
    """Enforce: min 8 chars, 1 uppercase, 1 lowercase, 1 digit."""
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError("password must be at most 128 bytes")
    if not any(c.isupper() for c in password):
        raise ValueError("password must contain an uppercase letter")
    if not any(c.islower() for c in password):
        raise ValueError("password must contain a lowercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("password must contain a digit")
    return password


class UserRegister(BaseModel):
    username: str
    password: str

    _clean_username_field = field_validator("username")(_clean_username)
    _password_complexity = field_validator("password")(_check_password_complexity)


class UserLogin(BaseModel):
    # No complexity rules here — existing users must be able to log in
    # even if their password predates the policy.
    username: str
    password: str

    _clean_username_field = field_validator("username")(_clean_username)

    @field_validator("password")
    @classmethod
    def _password_length(cls, v: str) -> str:
        if not v or len(v.encode("utf-8")) > _MAX_PASSWORD_BYTES:
            raise ValueError("password must be 1-128 bytes")
        return v


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class User(BaseModel):
    username: str
    is_admin: bool = False


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _init_users_table() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT NOT NULL UNIQUE,
            hashed_password TEXT NOT NULL,
            is_admin  INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _get_user(username: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT username, hashed_password, is_admin FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    if row:
        return {"username": row[0], "hashed_password": row[1], "is_admin": bool(row[2])}
    return None


def get_user_record(username: str) -> dict[str, Any] | None:
    """Public lookup of a user record (username, is_admin) for token refresh."""
    _init_users_table()
    return _get_user(username)


def _create_user(username: str, hashed_password: str, is_admin: bool = False) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (username, hashed_password, is_admin) VALUES (?, ?, ?)",
            (username, hashed_password, int(is_admin)),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES],
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt()
    ).decode("utf-8")


def _create_token(
    data: dict[str, Any], expires_delta: timedelta, token_type: str
) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + expires_delta
    to_encode.update({"exp": expire, "type": token_type})
    return cast(str, jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM))


def create_access_token(username: str, is_admin: bool) -> str:
    """Short-lived access token (default 15 minutes)."""
    return _create_token(
        {"sub": username, "is_admin": is_admin},
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )


def create_refresh_token(username: str) -> str:
    """Long-lived refresh token (default 7 days)."""
    return _create_token(
        {"sub": username},
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
    )


def verify_refresh_token(token: str) -> dict[str, Any] | None:
    """Decode a refresh token and return its payload, or None if invalid.

    Only tokens with type == "refresh" are accepted — access tokens are
    rejected to keep the two flows separate.
    """
    try:
        payload: dict[str, Any] = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "refresh" or not payload.get("sub"):
        return None
    return payload


# ---------------------------------------------------------------------------
# Account lockout (5 failed attempts -> 30 min cooldown, in-memory)
# ---------------------------------------------------------------------------

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=30)

_lockout_lock = threading.Lock()
# username -> list of failed-attempt timestamps (pruned to the lockout window)
_failed_logins: dict[str, list[datetime]] = {}


def _prune_failures(username: str) -> list[datetime]:
    """Return failures still inside the lockout window for username."""
    now = datetime.now(UTC)
    attempts = [
        ts for ts in _failed_logins.get(username, []) if now - ts < LOCKOUT_DURATION
    ]
    if attempts:
        _failed_logins[username] = attempts
    else:
        _failed_logins.pop(username, None)
    return attempts


def is_account_locked(username: str) -> bool:
    """True when username has >= MAX_FAILED_ATTEMPTS failures in the window."""
    with _lockout_lock:
        return len(_prune_failures(username)) >= MAX_FAILED_ATTEMPTS


def record_failed_login(username: str) -> int:
    """Record a failed login; return failures so far in the window."""
    with _lockout_lock:
        attempts = _prune_failures(username)
        attempts.append(datetime.now(UTC))
        _failed_logins[username] = attempts
        return len(attempts)


def reset_failed_logins(username: str) -> None:
    """Clear the failure counter after a successful login."""
    with _lockout_lock:
        _failed_logins.pop(username, None)


# ---------------------------------------------------------------------------
# Public auth functions
# ---------------------------------------------------------------------------


def register_user(username: str, password: str) -> bool:
    """Register a new user. Returns True on success, False if username exists."""
    _init_users_table()
    hashed = _hash_password(password)
    return _create_user(username, hashed)


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Authenticate user and return a token dict, or None if invalid.

    Returns:
        {"access_token": ..., "refresh_token": ..., "token_type": "bearer"}
        on success, None on bad credentials.  Lockout bookkeeping is the
        caller's job (see is_account_locked / record_failed_login).
    """
    _init_users_table()
    user = _get_user(username)
    if not user or not _verify_password(password, user["hashed_password"]):
        return None
    return {
        "access_token": create_access_token(user["username"], user["is_admin"]),
        "refresh_token": create_refresh_token(user["username"]),
        "token_type": "bearer",
    }


def get_current_user(
    token: str = Depends(oauth2_scheme),
) -> User | None:
    """Dependency: extracts user from JWT token. Returns None if no token provided."""
    if token is None:
        return None
    try:
        payload: dict[str, Any] = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = cast(str | None, payload.get("sub"))
        if username is None:
            return None
        # Refresh tokens must not authenticate API requests.
        if payload.get("type") != "access":
            return None
        is_admin = payload.get("is_admin", False)
        return User(username=username, is_admin=is_admin)
    except JWTError:
        return None


def require_user(user: User | None = Depends(get_current_user)) -> User:
    """Dependency: requires a valid user. Returns 401 if not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Use /token to login.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(user: User | None = Depends(get_current_user)) -> User:
    """Dependency: requires an admin user."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return user
