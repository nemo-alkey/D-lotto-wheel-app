#!/usr/bin/env python3
"""
wheel_explorer.py — browse, filter, and select Bluskov wheels.

Logic layer behind the dashboard's "📚 Bluskov Library" tab. Data comes
from ``bluskov_wheel_library.WHEEL_REGISTRY`` (verified and pending
published systems) plus any user-added wheels persisted in
``data/user_wheels.json``.

Guarantee types follow the dropdown labels used by the UI::

    "4-if-4"        single 4-win if 4 pool numbers hit
    "5-if-5"        single 5-win if 5 pool numbers hit
    "Double 4-if-4" TWO 4-wins if 4 hit   (Bluskov #88-#90)
    "Triple 4-if-5" System #107 family
    "Six 4-if-5"    System #119 family

Auto-selection: for a guarantee type + pool size, the mathematically
minimal system is the one with the LOWEST ticket count (the systems
registered in bluskov_wheel_library.WHEEL_EXPLORER are minimal by
construction — Bluskov's published systems are proven minimal covers).

Selected wheels are persisted to the ``user_selected_wheels`` database
table and can be exported as CSV or a print-friendly monospace layout.

Usage:
    from wheel_explorer import (
        filter_wheels, get_recommended, save_selection,
        export_csv, format_print,
    )
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from bluskov_wheel_library import (
    BOOK_REFERENCE,
    WHEEL_EXPLORER,
    WHEEL_REGISTRY,
    get_optimal_wheel,
    substitute_numbers,
)

logger = logging.getLogger(__name__)

USER_WHEELS_PATH = Path(__file__).parent / "data" / "user_wheels.json"
DEFAULT_DB_PATH = str(Path(__file__).parent / "lotto.db")

#: UI guarantee labels -> WHEEL_EXPLORER keys
GUARANTEE_TYPES: dict[str, str] = {
    "4-if-4": "4-if-4",
    "5-if-5": "5-if-5",
    "Double 4-if-4": "double-4-if-4",
    "Triple 4-if-5": "triple-4-if-5",
    "Six 4-if-5": "six-4-if-5",
}


# ---------------------------------------------------------------------------
# Registry access (library + user-added)
# ---------------------------------------------------------------------------


def load_user_wheels(path: Path | str = USER_WHEELS_PATH) -> dict[str, dict]:
    """Load user-added wheels from data/user_wheels.json (empty if missing).

    Same entry shape as WHEEL_REGISTRY: system_number (use 0 for custom),
    numbers, tickets, guarantee, wheel (list of combinations).
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Could not parse %s — ignoring user wheels.", p)
        return {}


def get_all_wheels() -> dict[str, dict]:
    """Merged registry: Bluskov library + user-added wheels.

    Each entry gains: key, ready (combinations actually entered),
    and origin ("bluskov" | "user").
    """
    wheels: dict[str, dict] = {}
    for key, entry in WHEEL_REGISTRY.items():
        e = dict(entry)
        e["key"] = key
        e["ready"] = len(e["wheel"]) == e["tickets"]
        e["origin"] = "bluskov"
        wheels[key] = e
    for key, entry in load_user_wheels().items():
        if key in wheels:
            logger.warning("User wheel %r shadows a library key — skipped.", key)
            continue
        e = dict(entry)
        e["key"] = key
        e["ready"] = len(e.get("wheel", [])) == e.get("tickets", -1)
        e["origin"] = "user"
        wheels[key] = e
    return wheels


def is_minimal(entry: dict) -> bool:
    """True if the entry is the registered minimal system for its
    (guarantee type, pool size) — i.e. it's in WHEEL_EXPLORER and its
    combinations are verified (ready)."""
    if not entry.get("ready") or entry.get("origin") != "bluskov":
        return False
    for sizes in WHEEL_EXPLORER.values():
        for pool_size, key in sizes.items():
            if key == entry["key"] and pool_size == entry["numbers"]:
                return True
    return False


# ---------------------------------------------------------------------------
# Filtering / search / auto-selection
# ---------------------------------------------------------------------------


def filter_wheels(
    pool_range: tuple[int, int] = (6, 20),
    guarantee_label: str | None = None,
    ticket_range: tuple[int, int] = (1, 500),
    search: str = "",
) -> list[dict]:
    """Filter the merged registry by sidebar criteria.

    Args:
        pool_range: (min, max) pool size, inclusive (UI slider 6-20).
        guarantee_label: A GUARANTEE_TYPES label, or None for all types.
        ticket_range: (min, max) ticket count, inclusive.
        search: Free text matched against system number, registry key,
            and guarantee description (case-insensitive).

    Returns:
        Matching entries sorted by (pool size, ticket count).
    """
    wheels = list(get_all_wheels().values())

    if guarantee_label:
        gkey = GUARANTEE_TYPES.get(guarantee_label, guarantee_label)
        allowed = set(WHEEL_EXPLORER.get(gkey, {}).values())
        wheels = [w for w in wheels if w["key"] in allowed]

    wheels = [
        w
        for w in wheels
        if pool_range[0] <= w["numbers"] <= pool_range[1]
        and ticket_range[0] <= w["tickets"] <= ticket_range[1]
    ]

    if search.strip():
        q = search.strip().lower()
        wheels = [
            w
            for w in wheels
            if q in str(w["system_number"]).lower()
            or q in w["key"].lower()
            or q in w["guarantee"].lower()
        ]

    return sorted(wheels, key=lambda w: (w["numbers"], w["tickets"]))


def get_recommended(guarantee_label: str, pool_size: int) -> dict | None:
    """Auto-select the mathematically minimal system for guarantee + pool.

    The minimal system is the registry entry for that guarantee type with
    the lowest ticket count at the requested pool size. Returns None when
    the library has no system for the combination.
    """
    gkey = GUARANTEE_TYPES.get(guarantee_label, guarantee_label)
    try:
        entry = get_optimal_wheel(gkey, pool_size)
    except KeyError:
        return None
    entry["origin"] = "bluskov"
    return entry


# ---------------------------------------------------------------------------
# Selection persistence
# ---------------------------------------------------------------------------


def _init_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_selected_wheels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            wheel_key     TEXT NOT NULL,
            system_number INTEGER,
            pool_size     INTEGER NOT NULL,
            user_numbers  TEXT,
            tickets_json  TEXT NOT NULL,
            selected_at   TEXT NOT NULL
        )
    """)


def save_selection(
    wheel_key: str,
    user_numbers: list[int] | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Persist a wheel selection to user_selected_wheels.

    The wheel's generic combinations are substituted with ``user_numbers``
    (via bluskov_wheel_library.substitute_numbers) when provided — these
    substituted tickets are the base template the wheel generator / play
    flow consumes. Without user numbers the generic template is stored.

    Returns:
        The new row id.
    """
    wheels = get_all_wheels()
    if wheel_key not in wheels:
        raise KeyError(f"Unknown wheel key: {wheel_key!r}")
    entry = wheels[wheel_key]
    if not entry["ready"]:
        raise ValueError(
            f"System #{entry['system_number']} combinations are pending "
            f"transcription from {BOOK_REFERENCE} — cannot select it."
        )

    tickets = (
        substitute_numbers(entry["wheel"], user_numbers)
        if user_numbers
        else [list(t) for t in entry["wheel"]]
    )

    conn = sqlite3.connect(db_path)
    try:
        _init_table(conn)
        cur = conn.execute(
            "INSERT INTO user_selected_wheels "
            "(wheel_key, system_number, pool_size, user_numbers, tickets_json, selected_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                wheel_key,
                entry["system_number"],
                entry["numbers"],
                json.dumps(user_numbers) if user_numbers else None,
                json.dumps(tickets),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def load_selections(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return all saved wheel selections, newest first."""
    conn = sqlite3.connect(db_path)
    try:
        _init_table(conn)
        rows = conn.execute(
            "SELECT id, wheel_key, system_number, pool_size, user_numbers, "
            "tickets_json, selected_at FROM user_selected_wheels ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "wheel_key": r[1],
            "system_number": r[2],
            "pool_size": r[3],
            "user_numbers": json.loads(r[4]) if r[4] else None,
            "tickets": json.loads(r[5]),
            "selected_at": r[6],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_csv(tickets: list[list[int]]) -> str:
    """CSV export of wheel tickets: one ticket per row, n1..n6 columns."""
    buf = io.StringIO()
    width = max((len(t) for t in tickets), default=6)
    writer = csv.writer(buf)
    writer.writerow(["ticket"] + [f"n{i}" for i in range(1, width + 1)])
    for idx, t in enumerate(tickets, 1):
        writer.writerow([idx] + list(t))
    return buf.getvalue()


def format_print(tickets: list[list[int]], title: str = "") -> str:
    """Print-friendly monospace layout, 4 tickets per line, zero-padded."""
    cells = [" ".join(f"{n:02d}" for n in t) for t in tickets]
    lines = [f"  {c}" for c in cells]
    rows = ["   ".join(lines[i : i + 4]) for i in range(0, len(lines), 4)]
    header = f"{title}\n" if title else ""
    header += f"{len(tickets)} tickets\n" + "-" * 40 + "\n"
    return header + "\n".join(rows)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import tempfile

    # --- Filtering ---
    all_wheels = get_all_wheels()
    print(f"Registry: {len(all_wheels)} wheels")
    assert "double4_10" in all_wheels and all_wheels["double4_10"]["ready"]
    assert not all_wheels["double4_11"]["ready"], "#89 is pending transcription"

    dbl = filter_wheels(guarantee_label="Double 4-if-4")
    assert {w["key"] for w in dbl} == {"double4_10", "double4_11", "double4_12"}
    print(f"'Double 4-if-4' filter: {[w['key'] for w in dbl]}")

    narrow = filter_wheels(pool_range=(10, 10), ticket_range=(1, 40))
    assert [w["key"] for w in narrow] == ["double4_10"]

    hit = filter_wheels(search="88")
    assert [w["key"] for w in hit] == ["double4_10"]
    hit2 = filter_wheels(search="six 4-wins")
    assert [w["key"] for w in hit2] == ["six4_12"]
    print("Search by system number and description: OK")

    # --- Minimality / recommendation ---
    assert is_minimal(all_wheels["double4_10"])
    assert not is_minimal(all_wheels["double4_11"])  # pending -> not verified
    rec = get_recommended("Double 4-if-4", 10)
    assert rec["system_number"] == 88 and rec["ready"]
    assert get_recommended("4-if-4", 10) is None  # no such system in library
    print("Recommended minimal system for Double 4-if-4 / 10: #88")

    # --- Selection + substitution round-trip ---
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db")
        my_nums = [3, 7, 12, 14, 18, 22, 29, 33, 38, 40]
        row_id = save_selection("double4_10", my_nums, db_path=db)
        sels = load_selections(db_path=db)
        assert len(sels) == 1 and sels[0]["id"] == row_id
        tickets = sels[0]["tickets"]
        assert len(tickets) == 30
        pool_used = {n for t in tickets for n in t}
        assert pool_used == set(my_nums), "substituted tickets must use my numbers"
        print(f"Selection saved (id {row_id}); 30 substituted tickets over 10 numbers")

        # Pending system cannot be selected
        try:
            save_selection("double4_11", db_path=db)
            raise AssertionError("pending system should refuse selection")
        except ValueError as e:
            print(f"Pending system correctly refused: {e}")

    # --- Export ---
    csv_text = export_csv(tickets[:3])
    assert csv_text.splitlines()[0] == "ticket,n1,n2,n3,n4,n5,n6"
    assert len(csv_text.splitlines()) == 4
    printable = format_print(tickets[:8], title="System #88")
    assert "8 tickets" in printable and "03 07 12 14 18 40" in printable
    print("\nCSV sample:")
    print(csv_text)
    print("Print view sample:")
    print(printable)

    print("All wheel_explorer self-tests passed.")
