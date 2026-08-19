#!/usr/bin/env python3
"""
rotation_scheduler.py — Rotation Planner for NZ Lotto Powerball

Loads historical draws from lotto_working.db, computes Bayesian posterior
probabilities (Dirichlet-Multinomial) for numbers 1-40, and generates a
rotation plan. Each period covers 2 draws (one calendar week). At each
period boundary the weakest number is swapped out for the next-best
candidate from the Bayesian ranking.

Saves to rotation_plan.csv and rotation_history DB table.
Optionally sends the plan via email.

Usage:
    python3 rotation_scheduler.py                                          # print + save only
    python3 rotation_scheduler.py --send-email --to user@example.com       # + email
    python3 rotation_scheduler.py --send-email --to user@example.com --dry-run  # preview email

Environment variables (for email):
    SMTP_SERVER     Default: smtp.gmail.com
    SMTP_PORT       Default: 587
    SMTP_USERNAME   Your email address
    SMTP_PASSWORD   App password
    SMTP_FROM       From address (defaults to SMTP_USERNAME)

--------------------------------------------------
Cron job (runs every Monday at 8:00 AM)
--------------------------------------------------
    0 8 * * 1 cd /path/to/lotto-wheel-app && python3 rotation_scheduler.py \
        --send-email --to user@example.com >> rotation_scheduler.log 2>&1

--------------------------------------------------
Systemd timer (alternative to cron)
--------------------------------------------------
See the .service and .timer files at the end of this script, or create:

    /etc/systemd/system/lotto-rotation.service
    /etc/systemd/system/lotto-rotation.timer

Then:
    sudo systemctl daemon-reload
    sudo systemctl enable lotto-rotation.timer
    sudo systemctl start lotto-rotation.timer
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from email.message import EmailMessage
from typing import Any, cast

WORKING_DB = "lotto.db"  # unified schema: numbers TEXT, bonus, powerball
ROTATION_DB = "rotation_scheduler.db"
PERIODS = 6  # each period = 2 draws (one calendar week → 12 draws total)
POOL_SIZE = 11
DEFAULT_PB = 3
ALPHA = 1.0  # Dirichlet prior concentration


# ---------------------------------------------------------------------------
# 1. Load draws
# ---------------------------------------------------------------------------


def load_draws(db_path: str = WORKING_DB) -> list[tuple[tuple[int, ...], Any, int, str]]:
    """Return list of (numbers_tuple, powerball, bonus, date) from the DB."""
    if not os.path.exists(db_path):
        print(f"Error: database '{db_path}' not found.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT draw_date, numbers, bonus, powerball FROM draws ORDER BY draw_date"
    ).fetchall()
    conn.close()

    draws: list[tuple[tuple[int, ...], Any, int, str]] = []
    for r in rows:
        try:
            nums = tuple(int(x.strip()) for x in r["numbers"].split(","))
        except (ValueError, AttributeError):
            continue
        if len(nums) != 6:
            continue
        draws.append((nums, r["powerball"], r["bonus"] or 0, r["draw_date"]))
    return draws


# ---------------------------------------------------------------------------
# 2. Bayesian posterior probabilities
# ---------------------------------------------------------------------------


def bayesian_posterior(
    draws: list[tuple[tuple[int, ...], Any, int, str]], alpha: float = ALPHA
) -> dict[int, float]:
    """Dirichlet-Multinomial posterior P(number) for 1-40.

    Posterior mean:  (count_i + alpha) / (total + 40 * alpha)
    """
    counts: Counter[int] = Counter()
    for nums, _, _, _ in draws:
        for n in nums:
            counts[n] += 1

    total = sum(counts.values())
    posterior: dict[int, float] = {}
    for n in range(1, 41):
        posterior[n] = (counts.get(n, 0) + alpha) / (total + 40 * alpha)
    return posterior


# ---------------------------------------------------------------------------
# Bonus Bayesian predictor
# ---------------------------------------------------------------------------


def bonus_bayesian_predictor(
    draws: list[tuple[tuple[int, ...], Any, int, str]], k: int = 3
) -> list[tuple[int, float]]:
    """Return top-k bonus ball predictions using Dirichlet-Multinomial.

    Extracts bonus balls from draws and applies a symmetric Dirichlet prior
    (alpha=1.0) to compute posterior probabilities for numbers 1-40.
    """
    from predictions import BonusBayesian

    bonus_balls = []
    for _, _, bonus, _ in draws:
        if bonus and 1 <= bonus <= 40:
            bonus_balls.append(bonus)

    if not bonus_balls:
        return []

    model: Any = BonusBayesian(  # type: ignore[no-untyped-call]  # predictions.py is untyped
        bonus_balls, alpha=1.0
    )
    return cast(list[tuple[int, float]], model.predict_top_k(k))


# ---------------------------------------------------------------------------
# 3. Rotation schedule
# ---------------------------------------------------------------------------


def build_rotation(posterior: dict[int, float]) -> list[list[int]]:
    """Generate PERIODS pools of POOL_SIZE numbers.

    Period 1 gets the top 11 by Bayesian score.
    Each subsequent period swaps out the lowest-scoring number in the pool
    and brings in the next-best from the remaining candidates.
    """
    ranked = sorted(range(1, 41), key=lambda n: -posterior[n])

    pool1 = set(ranked[:POOL_SIZE])
    remaining = ranked[POOL_SIZE:]
    next_idx = 0

    schedule = [sorted(pool1)]

    for _period in range(2, PERIODS + 1):
        current = set(schedule[-1])
        if next_idx < len(remaining):
            worst = min(current, key=lambda n: posterior[n])
            current.remove(worst)
            current.add(remaining[next_idx])
            next_idx += 1
        schedule.append(sorted(current))

    return schedule


# ---------------------------------------------------------------------------
# 4. Output — terminal
# ---------------------------------------------------------------------------


def print_plan(
    schedule: list[list[int]],
    posterior: dict[int, float],
    bonus_picks: list[tuple[Any, ...]] | None = None,
) -> None:
    """Print the rotation plan as a formatted table."""
    print()
    tag = " + Bonus Picks" if bonus_picks else ""
    print(f"  Bayesian Rotation Plan -- NZ Lotto Powerball{tag}  (1 period = 2 draws)")
    print(f"  Recommended Powerball: {DEFAULT_PB}")
    print()
    print(
        f"  {'Period (2 draws)':>16s}  {'Numbers (11 per period)':^49s}  {'Weakest':>7s}  {'Incoming':>8s}"
        + ("  {'Bonus':>28s}" if bonus_picks else "")
    )
    print(f"  {'-'*(84 + (32 if bonus_picks else 0))}")

    previous_set: set[int] | None = None
    for i, period_nums in enumerate(schedule, 1):
        nums_str = "  ".join(f"{n:02d}" for n in period_nums)
        current_set = set(period_nums)

        weakest = ""
        incoming = ""
        if previous_set is not None:
            dropped = previous_set - current_set
            added = current_set - previous_set
            if dropped:
                weakest = f"out {min(dropped):02d}"
            if added:
                incoming = f"in {min(added):02d}"

        line = f"  Period {i:>1d}       {nums_str}    {weakest:>7s}  {incoming:>8s}"
        if bonus_picks:
            pk = bonus_picks[min(i - 1, len(bonus_picks) - 1)]
            line += f"  pri {pk[0]:02d} ({pk[1]:.1%})"
            if len(bonus_picks) > 1:
                pk2 = bonus_picks[min(i, len(bonus_picks) - 1)]
                line += f"  sec {pk2[0]:02d} ({pk2[1]:.1%})"
        print(line)
        previous_set = current_set

    print()

    ranked = sorted(range(1, 41), key=lambda n: -posterior[n])
    bars = []
    max_prob = posterior[ranked[0]] if ranked else 1
    for n in ranked[:20]:
        pct = posterior[n] / max_prob
        bar_len = round(pct * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        prob_str = f"{posterior[n]:.6f}"
        bars.append(f"    #{n:02d}  {bar}  {prob_str}")

    print("  Top 20 Bayesian probabilities:")
    print(f"  {'-'*52}")
    for line in bars:
        print(line)
    print()


# ---------------------------------------------------------------------------
# 4b. Output — CSV
# ---------------------------------------------------------------------------


def save_plan_csv(
    schedule: list[list[int]],
    path: str = "rotation_plan.csv",
    bonus_picks: list[tuple[Any, ...]] | None = None,
) -> None:
    """Save the rotation plan to a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        header = [
            "Period",
            "Number_1",
            "Number_2",
            "Number_3",
            "Number_4",
            "Number_5",
            "Number_6",
            "Number_7",
            "Number_8",
            "Number_9",
            "Number_10",
            "Number_11",
            "Powerball",
        ]
        if bonus_picks:
            header += ["Bonus_Primary", "Bonus_Secondary", "Bonus_Tertiary"]
        writer.writerow(header)
        for i, period_nums in enumerate(schedule, 1):
            row = [i, *period_nums, DEFAULT_PB]
            if bonus_picks and i <= len(bonus_picks):
                row += [
                    bonus_picks[i - 1][0],
                    bonus_picks[min(i, len(bonus_picks) - 1)][0],
                    bonus_picks[min(i + 1, len(bonus_picks) - 1)][0],
                ]
            writer.writerow(row)
    print(f"  Saved rotation plan to {path}")


def save_plan_json(
    schedule: list[list[int]],
    path: str = "rotation_plan.json",
    bonus_picks: list[tuple[Any, ...]] | None = None,
) -> None:
    """Save the rotation plan as a structured JSON file."""
    from datetime import timedelta

    start = datetime.now()
    periods = []
    for i, nums in enumerate(schedule, 1):
        period_start = start + timedelta(weeks=i - 1)
        period_end = period_start + timedelta(days=13)
        entry: dict[str, Any] = {
            "start_date": period_start.strftime("%Y-%m-%d"),
            "end_date": period_end.strftime("%Y-%m-%d"),
            "main_pool": nums,
        }
        if bonus_picks:
            pk = bonus_picks[min(i - 1, len(bonus_picks) - 1)]
            entry["bonus_picks"] = {
                "primary": pk[0],
                "secondary": pk[1] if len(pk) > 1 else None,
                "tertiary": pk[2] if len(pk) > 2 else None,
            }
        periods.append(entry)

    output = {"periods": periods}
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Saved rotation plan to {path}")


# ---------------------------------------------------------------------------
# 4c. Output — database (rotation_history)
# ---------------------------------------------------------------------------


def init_rotation_db(db_path: str = ROTATION_DB) -> sqlite3.Connection:
    """Create rotation_history table if it doesn't exist and return connection."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rotation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            period INTEGER NOT NULL CHECK (period >= 1),
            numbers TEXT NOT NULL,
            powerball INTEGER NOT NULL CHECK (powerball BETWEEN 1 AND 10)
        )
    """)
    conn.commit()
    return conn


def save_plan_db(
    schedule: list[list[int]],
    db_path: str = ROTATION_DB,
) -> None:
    """Save each period's numbers as a row in rotation_history."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = init_rotation_db(db_path)
    for i, period_nums in enumerate(schedule, 1):
        numbers_str = ",".join(str(n) for n in period_nums)
        conn.execute(
            "INSERT INTO rotation_history (created_at, period, numbers, powerball) "
            "VALUES (?, ?, ?, ?)",
            (now, i, numbers_str, DEFAULT_PB),
        )
    conn.commit()
    conn.close()
    print(f"  Saved {len(schedule)} periods to rotation_history in {db_path}")


# ---------------------------------------------------------------------------
# 5. Email
# ---------------------------------------------------------------------------


def build_email_body(
    schedule: list[list[int]], bonus_picks: list[tuple[int, float]] | None = None
) -> str:
    """Build a plain-text email body from the rotation plan."""
    lines = []
    lines.append("=" * 56)
    lines.append("  NZ Lotto Powerball — Weekly Rotation Plan")
    lines.append("=" * 56)
    lines.append("")
    lines.append(f"  Generated:  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  Pool size:  {POOL_SIZE} numbers per period")
    lines.append(f"  Periods:    {PERIODS}  ({PERIODS * 2} draws)")
    lines.append(f"  Powerball:  {DEFAULT_PB}")
    lines.append("")

    previous_set: set[int] | None = None
    for i, period_nums in enumerate(schedule, 1):
        nums_str = ", ".join(f"{n:02d}" for n in period_nums)
        line = f"  Period {i}:  {nums_str}"
        if previous_set is not None:
            dropped = previous_set - set(period_nums)
            added = set(period_nums) - previous_set
            changes = []
            if dropped:
                changes.append(f"drop {min(dropped):02d}")
            if added:
                changes.append(f"add {min(added):02d}")
            if changes:
                line += f"  ({'; '.join(changes)})"
        lines.append(line)
        if bonus_picks:
            pk = bonus_picks[min(i - 1, len(bonus_picks) - 1)]
            line_bonus = f"         Bonus picks: pri #{pk[0]:02d} ({pk[1]:.1%})"
            lines.append(line_bonus)
        previous_set = set(period_nums)

    lines.append("")
    lines.append("-" * 56)
    lines.append("  Lotto Rotation Scheduler")
    return "\n".join(lines)


def send_email(
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """Send an email via SMTP (STARTTLS). Configure via env vars."""
    server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", 587))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", username)

    if not username or not password:
        print(
            "Error: SMTP_USERNAME and SMTP_PASSWORD environment variables "
            "must be set to send email."
        )
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
# 6. Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and distribute the NZ Lotto rotation plan.",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send the plan via email",
    )
    parser.add_argument(
        "--to",
        help="Email recipient (required with --send-email)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the email body without sending",
    )
    parser.add_argument(
        "--include-bonus",
        action="store_true",
        help="Include top-3 bonus ball Bayesian predictions per period",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also save the plan as a structured JSON file",
    )
    args = parser.parse_args()

    if args.send_email and not args.to:
        print("Error: --send-email requires --to <email>.")
        sys.exit(1)

    # --- Generate plan ---
    print("  Loading draws...", end=" ", flush=True)
    draws = load_draws()
    print(f"{len(draws)} draws loaded.")

    print("  Computing Bayesian posteriors...", end=" ", flush=True)
    posterior = bayesian_posterior(draws)
    print("done.")
    print(f"  Draws used:      {len(draws)}")
    print(f"  Pool size:       {POOL_SIZE} numbers per period")
    print(f"  Periods:         {PERIODS}  ({PERIODS * 2} draws @ 2 draws/period)")
    print(f"  Prior alpha:     {ALPHA}")

    schedule = build_rotation(posterior)

    # --- Bonus picks ---
    bonus_picks = None
    if args.include_bonus:
        print("  Computing bonus ball predictions...", end=" ", flush=True)
        bonus_picks = bonus_bayesian_predictor(draws, k=3)
        print(f"top-3: {[f'#{n} ({p:.1%})' for n, p in bonus_picks]}")

    # --- Terminal output ---
    print_plan(schedule, posterior, bonus_picks=bonus_picks)

    # --- CSV ---
    save_plan_csv(schedule, bonus_picks=bonus_picks)

    # --- JSON ---
    if args.json:
        save_plan_json(schedule, bonus_picks=bonus_picks)

    # --- Database ---
    save_plan_db(schedule)

    # --- Email ---
    if args.send_email:
        subject = f"NZ Lotto Rotation Plan — {datetime.now().strftime('%Y-%m-%d')}"
        body = build_email_body(schedule, bonus_picks=bonus_picks)

        if bonus_picks:
            bonus_tag = " (#" + ", #".join(str(pk[0]) for pk in bonus_picks[:3]) + ")"
            subject += bonus_tag

        if args.dry_run:
            print()
            print("=== DRY RUN — email preview ===")
            print(f"To:      {args.to}")
            print(f"Subject: {subject}")
            print()
            print(body)
            print("=== end dry run ===")
        else:
            print(f"  Sending email to {args.to}...", end=" ", flush=True)
            send_email(args.to, subject, body)
            print("done.")


if __name__ == "__main__":
    main()
