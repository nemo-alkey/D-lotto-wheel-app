#!/usr/bin/env python3
"""
alert.py — Check the latest draw against all wheels and send alerts on wins.

Usage:
    python3 alert.py --email you@example.com
    python3 alert.py --email you@example.com --draw "11,12,17,22,28,32" --pb 3
    python3 alert.py --email you@example.com --sms +64212345678 --dry-run

Environment variables for email (via .env or export):
    SMTP_SERVER     Default: smtp.gmail.com
    SMTP_PORT       Default: 587
    SMTP_USERNAME   Your email address (e.g. you@gmail.com)
    SMTP_PASSWORD   App password (not your regular password)
    SMTP_FROM       From address (defaults to SMTP_USERNAME)

--------------------------------------------------
Setting up Gmail with an App Password
--------------------------------------------------
1. Enable 2-Factor Authentication at https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Generate an app password for "Mail" and copy the 16-char code
4. Export it:

       export SMTP_USERNAME="you@gmail.com"
       export SMTP_PASSWORD="abcd efgh ijkl mnop"

   Or add to ~/.bashrc / ~/.profile:

       export SMTP_USERNAME="you@gmail.com"
       export SMTP_PASSWORD="abcd efgh ijkl mnop"

--------------------------------------------------
Cron job (runs Wed & Sat after draws ~7:30pm NZT)
--------------------------------------------------
   # Email only
   30 19 * * 3,6 cd /path/to/lotto-wheel-app && python3 alert.py --email you@example.com >> alert.log 2>&1

   # Email + SMS (requires Twilio setup — see send_sms placeholder)
   30 19 * * 3,6 cd /path/to/lotto-wheel-app && python3 alert.py --email you@example.com --sms +64212345678 >> alert.log 2>&1

The cron runs at 7:30 PM NZT — results are usually published by ~7:20 PM.
"""

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lotto_wheels import DIVISIONS, WHEELS, load_draws

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_ticket(
    ticket_nums: list[int] | tuple[int, ...],
    wheel_pb: int,
    draw_nums: list[int],
    draw_pb: int,
) -> int | None:
    """Return division index if the ticket wins, else None.

    A ticket qualifies for exactly one division — the highest it satisfies.
    """
    matches = len(set(ticket_nums) & set(draw_nums))
    pb_hit = wheel_pb == draw_pb
    for idx, (_, main_needed, pb_must_match, _) in enumerate(DIVISIONS):
        if matches == main_needed and pb_hit == pb_must_match:
            return idx
    return None


def check_wheel(
    name: str,
    tickets: list[tuple[int, ...]],
    wheel_pb: int,
    draw_nums: list[int],
    draw_pb: int,
) -> tuple[list[int], int]:
    """Check all tickets in a wheel. Returns (div_counts, total_prize)."""
    div_counts = [0] * len(DIVISIONS)
    for ticket in tickets:
        idx = score_ticket(ticket, wheel_pb, draw_nums, draw_pb)
        if idx is not None:
            div_counts[idx] += 1
    total_prize = sum(div_counts[i] * DIVISIONS[i][3] for i in range(len(DIVISIONS)))
    return div_counts, total_prize


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------


def build_message(
    results: list[tuple[str, list[int], int]],
    draw_nums: list[int],
    draw_pb: int,
    draw_date: str,
) -> str:
    """Build the alert body text."""
    lines = []
    lines.append("=" * 50)
    lines.append("  NZ Lotto Powerball — Wheel Alert")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"  Draw:  {', '.join(f'{n:02d}' for n in draw_nums)}  |  PB {draw_pb}")
    if draw_date:
        lines.append(f"  Date:  {draw_date}")
    lines.append("")

    any_win = False
    grand_total = 0
    for name, div_counts, total_prize in results:
        lines.append(f"  [{name}]")
        if total_prize > 0:
            any_win = True
            grand_total += total_prize
            for i, count in enumerate(div_counts):
                if count > 0:
                    label, _, _, prize = DIVISIONS[i]
                    subtotal = count * prize
                    lines.append(
                        f"         {label}: {count} × ${prize:>6,.0f} = ${subtotal:>8,.0f}"
                    )
            lines.append("         ─────────────────────────────────")
            lines.append(f"         Total: ${total_prize:>8,.0f}")
        else:
            lines.append("         No winning tickets")
        lines.append("")

    if any_win:
        lines.append(f"  >>> Grand total: ${grand_total:>8,.0f} <<<")
    else:
        lines.append("  No winning wheels for this draw.")

    lines.append("")
    lines.append("-" * 50)
    lines.append("  Lotto Wheel Alert System")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email (smtplib)
# ---------------------------------------------------------------------------


def send_email(recipient: str, subject: str, body: str) -> None:
    """Send an email via SMTP (STARTTLS). Configure via env vars."""
    server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 587))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", username)

    if not username or not password:
        print("Error: SMTP_USERNAME and SMTP_PASSWORD environment variables " "must be set.")
        sys.exit(1)

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = recipient

    with smtplib.SMTP(server, port) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(msg)


# ---------------------------------------------------------------------------
# SMS (Twilio placeholder)
# ---------------------------------------------------------------------------

TWILIO_ENABLED = False  # Set to True and install twilio package to enable

try:
    if TWILIO_ENABLED:
        from twilio.rest import Client
    else:
        Client = None
except ImportError:
    Client = None  # Twilio not installed — SMS falls through to placeholder


def send_sms(recipient: str, message: str) -> None:
    """Send an SMS via Twilio (placeholder unless configured)."""
    if Client is not None and TWILIO_ENABLED:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM")
        if not all([account_sid, auth_token, from_number]):
            print(
                "SMS: Twilio not configured — set TWILIO_ACCOUNT_SID, "
                "TWILIO_AUTH_TOKEN, TWILIO_FROM"
            )
            return
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=message,
            from_=from_number,
            to=recipient,
        )
        print(f"SMS sent to {recipient}")
    else:
        print(f"[SMS placeholder] Would send to {recipient}: {message[:120]}...")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def check_draw(
    draw_nums: list[int], draw_pb: int, draw_date: str
) -> list[tuple[str, list[int], int]]:
    """Run all wheels against a draw and return results list."""
    results = []
    for name, (tickets, wheel_pb) in WHEELS.items():
        div_counts, total_prize = check_wheel(name, tickets, wheel_pb, draw_nums, draw_pb)
        results.append((name, div_counts, total_prize))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check the latest draw against all wheels and send alerts.",
    )
    parser.add_argument(
        "--email",
        help="Recipient email address",
    )
    parser.add_argument(
        "--sms",
        help="Recipient phone number for SMS (requires Twilio setup)",
    )
    parser.add_argument(
        "--draw",
        help="Custom draw: 6 comma-separated numbers (use with --pb)",
        metavar="n1,n2,n3,n4,n5,n6",
    )
    parser.add_argument(
        "--pb",
        type=int,
        help="Powerball for custom draw (1–10)",
        metavar="N",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without sending anything",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.email and not args.sms:
        print("Provide at least one of --email or --sms (or --dry-run to preview).")
        sys.exit(1)

    # --- Resolve draw ---
    if args.draw:
        try:
            draw_nums = [int(x.strip()) for x in args.draw.split(",")]
            if (
                len(draw_nums) != 6
                or len(set(draw_nums)) != 6
                or any(n < 1 or n > 40 for n in draw_nums)
            ):
                raise ValueError
        except ValueError:
            print("Error: --draw must be 6 unique comma-separated numbers 1–40.")
            sys.exit(1)
        if args.pb is None or not (1 <= args.pb <= 10):
            print("Error: --pb is required and must be 1–10 when using --draw.")
            sys.exit(1)
        draw_pb = args.pb
        draw_date = "Custom"
    else:
        draws = load_draws()
        if not draws:
            print("No draws in database.")
            sys.exit(1)
        draw_nums, draw_pb, draw_bonus, draw_date = draws[-1]

    # --- Check ---
    results = check_draw(draw_nums, draw_pb, draw_date)
    total_all = sum(r[2] for r in results)

    if total_all > 0:
        subject = f"Lotto Alert: ${total_all:,.0f} won!"
    else:
        subject = "Lotto Alert: No wins this draw"

    body = build_message(results, draw_nums, draw_pb, draw_date)

    if args.dry_run:
        print(body)
        return

    if args.email:
        send_email(args.email, subject, body)
        print(f"Email sent to {args.email}")

    if args.sms:
        send_sms(
            args.sms,
            f"Lotto: ${total_all:,.0f} won" if total_all > 0 else "Lotto: No wins",
        )


if __name__ == "__main__":
    main()
