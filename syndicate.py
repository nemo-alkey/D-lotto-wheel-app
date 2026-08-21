#!/usr/bin/env python3
"""
syndicate.py — Multi-user lottery pool (syndicate) management.

A syndicate is a group of users who pool money for tickets and share any
winnings proportionally to their contribution percentage.

Schema (defined in database.py, created via the shared SQLAlchemy engine):
  - syndicates:         id, name, created_by, created_at, total_contribution
  - members:            id, syndicate_id, user_id, contribution_pct, email
  - syndicate_tickets:  id, syndicate_id, ticket_numbers (JSON),
                        draw_id, contributor_splits (JSON)

Integration:
  - auth.py: members reference users.id. NOTE: the users table has no email
    column, so member emails are stored on the members row itself (passed to
    add_member() or entered in the dashboard).
  - notifier.py: auto_notify_winners() emails each member via send_email_to()
    and logs every notification via log_alert().

Prize split rule: each member receives total_prize * contribution_pct /
sum(contribution_pct), rounded to 2 decimal places. Any rounding remainder
goes to the syndicate creator (created_by).
"""

from __future__ import annotations

import json
from typing import Any, cast

from sqlalchemy import text

from database import get_connection, initialize_database

NUMBERS_PER_TICKET = 6
MIN_NUMBER = 1
MAX_NUMBER = 40


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_schema() -> None:
    """Create the syndicate tables if they don't exist yet."""
    initialize_database()


def _refresh_total_contribution(conn: Any, syndicate_id: int) -> None:
    """Keep syndicates.total_contribution = sum of member percentages."""
    conn.execute(
        text(
            "UPDATE syndicates SET total_contribution = "
            "(SELECT COALESCE(SUM(contribution_pct), 0) FROM members "
            " WHERE syndicate_id = :sid) WHERE id = :sid"
        ),
        {"sid": syndicate_id},
    )


def _validate_ticket(ticket_numbers: list[int]) -> list[int]:
    """Validate and normalize a ticket (sorted list of unique ints)."""
    nums = sorted(int(n) for n in ticket_numbers)
    if len(nums) != NUMBERS_PER_TICKET:
        raise ValueError(f"A ticket needs exactly {NUMBERS_PER_TICKET} numbers.")
    if len(set(nums)) != NUMBERS_PER_TICKET:
        raise ValueError("Duplicate numbers in ticket.")
    if any(n < MIN_NUMBER or n > MAX_NUMBER for n in nums):
        raise ValueError(f"Numbers must be between {MIN_NUMBER} and {MAX_NUMBER}.")
    return nums


# ---------------------------------------------------------------------------
# Syndicate CRUD
# ---------------------------------------------------------------------------


def create_syndicate(name: str, created_by_user_id: int) -> int:
    """Create a new syndicate.

    Args:
        name: Display name of the syndicate.
        created_by_user_id: auth users.id of the creator. The creator
            receives any prize-split rounding remainder.

    Returns:
        The new syndicate id.
    """
    if not name or not name.strip():
        raise ValueError("Syndicate name must not be empty.")

    _ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            text("INSERT INTO syndicates (name, created_by) VALUES (:name, :cb)"),
            {"name": name.strip(), "cb": int(created_by_user_id)},
        )
        conn.commit()
        return int(result.lastrowid)


def get_syndicate(syndicate_id: int) -> dict[str, Any] | None:
    """Return one syndicate as a dict, or None if it doesn't exist."""
    _ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            text(
                "SELECT id, name, created_by, created_at, total_contribution "
                "FROM syndicates WHERE id = :sid"
            ),
            {"sid": syndicate_id},
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "created_by": row[2],
        "created_at": row[3],
        "total_contribution": row[4],
    }


def list_syndicates() -> list[dict[str, Any]]:
    """Return all syndicates (id, name, creator, created_at, member count)."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            text(
                "SELECT s.id, s.name, s.created_by, s.created_at, "
                "s.total_contribution, COUNT(m.id) AS member_count "
                "FROM syndicates s LEFT JOIN members m ON m.syndicate_id = s.id "
                "GROUP BY s.id ORDER BY s.id ASC"
            )
        ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "created_by": r[2],
            "created_at": r[3],
            "total_contribution": r[4],
            "member_count": r[5],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def add_member(
    syndicate_id: int,
    user_id: int,
    contribution_pct: float,
    email: str | None = None,
) -> None:
    """Add a member to a syndicate (or update their share if already present).

    Args:
        syndicate_id: Target syndicate id.
        user_id: auth users.id of the member.
        contribution_pct: Member's share of the pool in percent (> 0).
            Percentages across members do not have to sum to 100 — prize
            splits are normalized by the actual sum.
        email: Contact email for winner notifications (stored on the member
            row; the auth users table has no email column).
    """
    if contribution_pct <= 0:
        raise ValueError("contribution_pct must be positive.")
    if get_syndicate(syndicate_id) is None:
        raise ValueError(f"Syndicate {syndicate_id} does not exist.")

    with get_connection() as conn:
        conn.execute(
            text(
                "INSERT INTO members (syndicate_id, user_id, contribution_pct, email) "
                "VALUES (:sid, :uid, :pct, :email) "
                "ON CONFLICT(syndicate_id, user_id) DO UPDATE SET "
                "contribution_pct = excluded.contribution_pct, email = excluded.email"
            ),
            {
                "sid": syndicate_id,
                "uid": int(user_id),
                "pct": float(contribution_pct),
                "email": email,
            },
        )
        _refresh_total_contribution(conn, syndicate_id)
        conn.commit()


def remove_member(syndicate_id: int, user_id: int) -> bool:
    """Remove a member from a syndicate. Returns True if a row was deleted."""
    _ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            text("DELETE FROM members WHERE syndicate_id = :sid AND user_id = :uid"),
            {"sid": syndicate_id, "uid": int(user_id)},
        )
        _refresh_total_contribution(conn, syndicate_id)
        conn.commit()
        return result.rowcount > 0


def get_members(syndicate_id: int) -> list[dict[str, Any]]:
    """Return all members of a syndicate (user_id, contribution_pct, email)."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            text(
                "SELECT user_id, contribution_pct, email FROM members "
                "WHERE syndicate_id = :sid ORDER BY user_id ASC"
            ),
            {"sid": syndicate_id},
        ).fetchall()
    return [{"user_id": r[0], "contribution_pct": r[1], "email": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


def add_ticket(
    syndicate_id: int,
    ticket_numbers: list[int],
    draw_id: str,
    contributor_splits: dict[int, float] | None = None,
) -> int:
    """Register a ticket played by the syndicate for a draw.

    Args:
        syndicate_id: Owning syndicate id.
        ticket_numbers: The 6 numbers on the ticket.
        draw_id: Draw identifier (e.g. draw date 'YYYY-MM-DD').
        contributor_splits: Optional per-ticket mapping {user_id: pct} of who
            paid for THIS ticket. Defaults to the members' contribution_pct
            normalized to 100. Stored as metadata; prize splits are always
            computed from member contribution_pct (see calculate_prize_split).

    Returns:
        The new ticket id.
    """
    nums = _validate_ticket(ticket_numbers)
    if not draw_id or not str(draw_id).strip():
        raise ValueError("draw_id must not be empty.")
    if get_syndicate(syndicate_id) is None:
        raise ValueError(f"Syndicate {syndicate_id} does not exist.")

    if contributor_splits is None:
        members = get_members(syndicate_id)
        total_pct = sum(m["contribution_pct"] for m in members)
        contributor_splits = (
            {m["user_id"]: round(m["contribution_pct"] / total_pct * 100, 4) for m in members}
            if total_pct > 0
            else {}
        )

    with get_connection() as conn:
        result = conn.execute(
            text(
                "INSERT INTO syndicate_tickets "
                "(syndicate_id, ticket_numbers, draw_id, contributor_splits) "
                "VALUES (:sid, :nums, :did, :splits)"
            ),
            {
                "sid": syndicate_id,
                "nums": json.dumps(nums),
                "did": str(draw_id).strip(),
                "splits": json.dumps({str(k): v for k, v in contributor_splits.items()}),
            },
        )
        conn.commit()
        return int(result.lastrowid)


def get_tickets(syndicate_id: int, draw_id: str | None = None) -> list[dict[str, Any]]:
    """Return a syndicate's tickets, optionally filtered by draw_id."""
    _ensure_schema()
    query = (
        "SELECT id, ticket_numbers, draw_id, contributor_splits "
        "FROM syndicate_tickets WHERE syndicate_id = :sid"
    )
    params: dict[str, Any] = {"sid": syndicate_id}
    if draw_id is not None:
        query += " AND draw_id = :did"
        params["did"] = str(draw_id)
    query += " ORDER BY id ASC"
    with get_connection() as conn:
        rows = conn.execute(text(query), params).fetchall()
    return [
        {
            "id": r[0],
            "ticket_numbers": json.loads(r[1]),
            "draw_id": r[2],
            "contributor_splits": json.loads(r[3]) if r[3] else {},
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Prize split
# ---------------------------------------------------------------------------


def calculate_prize_split(syndicate_id: int, total_prize: float) -> dict[int, float]:
    """Split a prize proportionally to member contribution percentages.

    Each share is total_prize * contribution_pct / sum(contribution_pct),
    rounded to 2 decimal places. The rounding remainder (positive or
    negative) goes to the syndicate creator.

    Args:
        syndicate_id: Syndicate id.
        total_prize: Total prize amount to split (>= 0).

    Returns:
        Dict mapping user_id -> prize amount.
    """
    if total_prize < 0:
        raise ValueError("total_prize must be non-negative.")

    syndicate = get_syndicate(syndicate_id)
    if syndicate is None:
        raise ValueError(f"Syndicate {syndicate_id} does not exist.")

    members = get_members(syndicate_id)
    if not members:
        raise ValueError(f"Syndicate {syndicate_id} has no members.")

    total_pct = sum(m["contribution_pct"] for m in members)
    if total_pct <= 0:
        raise ValueError("Member contribution percentages sum to zero.")

    splits: dict[int, float] = {}
    for m in members:
        splits[m["user_id"]] = round(total_prize * m["contribution_pct"] / total_pct, 2)

    remainder = round(total_prize - sum(splits.values()), 2)
    creator = syndicate["created_by"]
    splits[creator] = round(splits.get(creator, 0.0) + remainder, 2)
    return splits


# ---------------------------------------------------------------------------
# Winner notification
# ---------------------------------------------------------------------------


def auto_notify_winners(syndicate_id: int, draw_results: dict[str, Any]) -> dict[str, Any]:
    """Notify all members of their prize share via notifier.py email.

    Args:
        syndicate_id: Syndicate id.
        draw_results: Dict describing the outcome. Recognized keys:
            "total_prize" (or "prize") — amount to split (required, > 0 to
            send notifications), "draw_date"/"draw_id" — used in the message.

    Returns:
        Summary dict: splits per user, and per-user notified flags. Members
        without an email (or when SMTP is unconfigured) get notified=False;
        everything is still written to the alert log via notifier.log_alert.
    """
    import notifier

    total_prize = float(draw_results.get("total_prize") or draw_results.get("prize") or 0.0)
    draw_label = draw_results.get("draw_date") or draw_results.get("draw_id") or "unknown draw"

    splits = calculate_prize_split(syndicate_id, total_prize)
    members = {m["user_id"]: m for m in get_members(syndicate_id)}
    syndicate = cast(dict[str, Any], get_syndicate(syndicate_id))

    notified: dict[int, bool] = {}
    for user_id, amount in splits.items():
        email = members.get(user_id, {}).get("email")
        subject = f"Syndicate win: ${amount:,.2f} share ({draw_label})"
        body = (
            f"Good news — your syndicate '{syndicate['name']}' won "
            f"${total_prize:,.2f} in {draw_label}.\n\n"
            f"Your share: ${amount:,.2f}\n\n"
            f"— Lotto Wheel App"
        )
        if email:
            notified[user_id] = notifier.send_email_to(email, subject, body)
        else:
            notifier.log_alert(
                f"Syndicate {syndicate_id}: user {user_id} won ${amount:,.2f} "
                f"but has no email on file — not notified.",
                "WARN",
            )
            notified[user_id] = False

    notifier.log_alert(
        f"SYNDICATE WIN: '{syndicate['name']}' (id {syndicate_id}) — "
        f"${total_prize:,.2f} in {draw_label}; splits: {splits}",
        "ALERT",
    )

    return {
        "syndicate_id": syndicate_id,
        "draw": draw_label,
        "total_prize": total_prize,
        "splits": splits,
        "notified": notified,
    }
