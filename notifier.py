#!/usr/bin/env python3
"""
notifier.py — Email, desktop, and file-based notification for lotto alerts.

Supports:
  - Email via SMTP (configured via environment variables).
  - Windows toast notification via plyer (optional, graceful fallback).
  - Log file for all alerts.

Environment variables:
  SMTP_SERVER     Default: smtp.gmail.com
  SMTP_PORT       Default: 587
  SMTP_USERNAME   Your email address
  SMTP_PASSWORD   App password
  SMTP_FROM       From address (defaults to SMTP_USERNAME)
  ALERT_LOG       Path to alert log file (default: alert.log)
  ALERT_EMAIL_TO  Recipient for email alerts
"""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

try:
    from settings import settings

    ALERT_LOG = settings.alert_log
except ImportError:
    ALERT_LOG = os.environ.get("ALERT_LOG", "alert.log")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log_alert(message: str, level: str = "INFO") -> None:
    """Append a timestamped alert entry to the log file."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{level}] {message}\n")


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def _get_smtp_config() -> dict[str, Any]:
    """Return SMTP configuration from settings or environment."""
    try:
        from settings import settings

        return {
            "server": settings.smtp_server,
            "port": settings.smtp_port,
            "username": settings.smtp_username,
            "password": settings.smtp_password,
            "from_addr": settings.smtp_from or settings.smtp_username,
            "to_addr": settings.alert_email_to or settings.smtp_username,
        }
    except ImportError:
        return {
            "server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
            "port": int(os.environ.get("SMTP_PORT", 587)),
            "username": os.environ.get("SMTP_USERNAME"),
            "password": os.environ.get("SMTP_PASSWORD"),
            "from_addr": os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME"),
            "to_addr": os.environ.get("ALERT_EMAIL_TO") or os.environ.get("SMTP_USERNAME"),
        }


def send_email_alert(subject: str, body: str) -> bool:
    """Send an email alert via SMTP.

    Returns True on success, False on failure.
    """
    cfg = _get_smtp_config()
    server = cfg["server"]
    port = cfg["port"]
    username = cfg["username"]
    password = cfg["password"]
    from_addr = cfg["from_addr"]
    to_addr = cfg["to_addr"]

    if not username or not password:
        log_alert("Email alert skipped: SMTP credentials not configured.", "WARN")
        return False

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        with smtplib.SMTP(server, port) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)

        log_alert(f"Email sent: {subject}", "INFO")
        return True
    except Exception as exc:
        log_alert(f"Email failed: {exc}", "ERROR")
        return False


def send_email_to(to_addr: str, subject: str, body: str) -> bool:
    """Send an email to a specific recipient via the configured SMTP account.

    Unlike send_email_alert (which mails the configured admin address), this
    targets an arbitrary recipient — used by syndicate winner notifications.

    Returns True on success, False on failure.
    """
    cfg = _get_smtp_config()

    if not cfg["username"] or not cfg["password"]:
        log_alert(f"Email to {to_addr} skipped: SMTP credentials not configured.", "WARN")
        return False

    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = cfg["from_addr"]
        msg["To"] = to_addr

        with smtplib.SMTP(cfg["server"], cfg["port"]) as smtp:
            smtp.starttls()
            smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(msg)

        log_alert(f"Email sent to {to_addr}: {subject}", "INFO")
        return True
    except Exception as exc:
        log_alert(f"Email to {to_addr} failed: {exc}", "ERROR")
        return False


# ---------------------------------------------------------------------------
# Desktop notification (Windows toast)
# ---------------------------------------------------------------------------


def send_desktop_notification(title: str, message: str) -> bool:
    """Show a Windows toast notification.

    Uses plyer if available; falls back gracefully.
    Returns True on success, False if unavailable.
    """
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            app_name="Lotto Wheel App",
            timeout=10,
        )
        log_alert(f"Desktop notification: {title}", "INFO")
        return True
    except ImportError:
        log_alert("Desktop notification skipped: plyer not installed.", "DEBUG")
        return False
    except Exception as exc:
        log_alert(f"Desktop notification failed: {exc}", "WARN")
        return False


# ---------------------------------------------------------------------------
# High-level alert
# ---------------------------------------------------------------------------


def send_alert(subject: str, body: str) -> None:
    """Send an alert through all configured channels.

    Logs to file, sends email if configured, shows desktop toast if available.
    """
    log_alert(f"ALERT: {subject}\n{body}", "ALERT")
    send_email_alert(subject, body)
    send_desktop_notification(subject, body[:200])


def notify_new_draw(
    draw_date: str, numbers: list[int], bonus: int, pb: int, source: str = "API"
) -> None:
    """Send notification that a new draw has been imported.

    Parameters
    ----------
    draw_date : str
        ISO date string (YYYY-MM-DD).
    numbers : list[int]
        Six main numbers.
    bonus : int
        Bonus ball number.
    pb : int
        Powerball number.
    source : str
        Data source (API, HTML, Selenium, CSV).
    """
    nums_str = ", ".join(f"{n:02d}" for n in numbers)
    subject = f"New Draw Imported: {draw_date}"
    body = (
        f"Source: {source}\n"
        f"Date: {draw_date}\n"
        f"Numbers: {nums_str}\n"
        f"Bonus: {bonus:02d}\n"
        f"Powerball: {pb}"
    )
    log_alert(f"NEW DRAW: {draw_date} — {nums_str} Bonus:{bonus} PB:{pb} [{source}]", "INFO")
    send_email_alert(subject, body)
    send_desktop_notification(subject, body)


# ---------------------------------------------------------------------------
# Draw results notification
# ---------------------------------------------------------------------------


def notify_draw_results(
    draw_date: str,
    numbers: list[int],
    bonus: int,
    pb: int,
    results_summary: list[dict[str, Any]],
) -> None:
    """Send a concise summary of which wheels won which divisions.

    Parameters
    ----------
    draw_date : str
        ISO date of the draw (YYYY-MM-DD).
    numbers : list[int]
        Six main numbers drawn.
    bonus : int
        Bonus ball number.
    pb : int
        Powerball number.
    results_summary : list[dict]
        Each dict should have keys: wheel_name, division, matches,
        bonus_match, ticket_count, prize_estimate.
    """
    nums_str = ", ".join(f"{n:02d}" for n in numbers)

    subject = f"Lotto Results: {draw_date} — {len(results_summary)} wheel(s) won"
    body_lines = [
        f"NZ Lotto Draw: {draw_date}",
        f"Numbers: {nums_str}  |  Bonus: {bonus:02d}  |  PB: {pb}",
        "",
    ]

    if not results_summary:
        body_lines.append("No wheels had winning tickets this draw.")
    else:
        body_lines.append(f"{'─' * 50}")
        body_lines.append(
            f"{'Wheel':<16s} {'Div':>4s} {'Matches':>7s} {'Bonus':>6s} {'Tickets':>8s} {'Est Prize':>10s}"
        )
        body_lines.append(f"{'─' * 50}")
        for r in results_summary:
            bonus_tag = "Yes" if r.get("bonus_match") else "—"
            body_lines.append(
                f"{r.get('wheel_name', '?'):<16s} "
                f"{r.get('division', '?'):>4s} "
                f"{r.get('matches', 0):>7d} "
                f"{bonus_tag:>6s} "
                f"{r.get('ticket_count', 0):>8d} "
                f"${r.get('prize_estimate', 0):>9,.0f}"
            )
        body_lines.append(f"{'─' * 50}")

    body = "\n".join(body_lines)
    log_alert(f"RESULTS: {draw_date} — {len(results_summary)} wheel(s) won", "ALERT")
    send_email_alert(subject, body)
    send_desktop_notification(subject, body[:200])


# ---------------------------------------------------------------------------
# Notification settings persistence (SQLite via SQLAlchemy)
# ---------------------------------------------------------------------------


def _get_settings_conn() -> Connection:
    """Return a database connection for the notifier_settings table."""
    from database_engine import get_engine

    engine = get_engine()
    conn = engine.connect()
    # Ensure table exists
    from sqlalchemy import text

    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS notifier_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    )
    conn.commit()
    return conn


def get_notifier_setting(key: str, default: str = "") -> str:
    """Read a value from the notifier_settings table."""
    from sqlalchemy import text

    conn = _get_settings_conn()
    result = conn.execute(
        text("SELECT value FROM notifier_settings WHERE key = :key"),
        {"key": key},
    )
    row = result.fetchone()
    conn.close()
    return str(row[0]) if row else default


def set_notifier_setting(key: str, value: str) -> None:
    """Write a value to the notifier_settings table (upsert)."""
    from sqlalchemy import text

    conn = _get_settings_conn()
    conn.execute(
        text(
            "INSERT INTO notifier_settings (key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = :value2"
        ),
        {"key": key, "value": value, "value2": value},
    )
    conn.commit()
    conn.close()


def get_all_notifier_settings() -> dict[str, str]:
    """Return all notifier settings as a dict."""
    from sqlalchemy import text

    conn = _get_settings_conn()
    result = conn.execute(text("SELECT key, value FROM notifier_settings"))
    settings_dict = {row[0]: row[1] for row in result.fetchall()}
    conn.close()
    return settings_dict
