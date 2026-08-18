#!/usr/bin/env python3
"""
csv_importer.py — Import lottery draw data from external CSV files.

Supports common formats from Kaggle, data.gov, and other sources.
Auto-detects column mappings based on header names and normalises
data into the unified lotto.db schema.

Usage:
    python csv_importer.py input.csv --date-col Date --numbers-col Numbers
    python csv_importer.py input.csv --auto  # auto-detect columns
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import os
import re
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto.db")

# Common column name patterns for auto-detection
DATE_PATTERNS = ["draw_date", "date", "drawdate", "draw date"]
NUMBERS_PATTERNS = ["numbers", "main_numbers", "winning_numbers", "main", "balls", "result"]
BONUS_PATTERNS = ["bonus", "bonus_ball", "bonusball", "supplementary"]
PB_PATTERNS = ["powerball", "power_ball", "pb", "power ball"]


def _normalise(name: str) -> str:
    """Strip whitespace, lowercase, replace underscores/spaces."""
    return re.sub(r"[_\s]+", "", name.lower())


def _auto_detect_columns(headers: list[str]) -> dict[str, str]:
    """Detect column names for date, numbers, bonus, powerball."""
    mapping: dict[str, str] = {}
    norm_headers = {_normalise(h): h for h in headers}

    # Date
    for pat in DATE_PATTERNS:
        if _normalise(pat) in norm_headers:
            mapping["date"] = norm_headers[_normalise(pat)]
            break

    # Numbers
    for pat in NUMBERS_PATTERNS:
        if _normalise(pat) in norm_headers:
            mapping["numbers"] = norm_headers[_normalise(pat)]
            break

    # Bonus
    for pat in BONUS_PATTERNS:
        if _normalise(pat) in norm_headers:
            mapping["bonus"] = norm_headers[_normalise(pat)]
            break

    # Powerball
    for pat in PB_PATTERNS:
        if _normalise(pat) in norm_headers:
            mapping["powerball"] = norm_headers[_normalise(pat)]
            break

    return mapping


def _parse_numbers(value: str) -> list[int]:
    """Parse numbers from various formats: '1 2 3 4 5 6', '1,2,3,4,5,6', '[1,2,3]'."""
    cleaned = re.sub(r"[\[\]\{\}]", "", value)
    parts = re.split(r"[\s,;|]+", cleaned.strip())
    return [int(p) for p in parts if p.strip().lstrip("-").isdigit()]


def import_csv(
    filepath: str,
    date_col: str | None = None,
    numbers_col: str | None = None,
    bonus_col: str | None = None,
    pb_col: str | None = None,
    auto: bool = False,
) -> int:
    """Import draws from a CSV file into lotto.db.

    Parameters
    ----------
    filepath : str
        Path to the CSV file.
    date_col, numbers_col, bonus_col, pb_col : str or None
        Explicit column names. If None and auto=True, auto-detected.
    auto : bool
        Auto-detect column mappings from header names.

    Returns
    -------
    int
        Number of draws imported.
    """
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draws (
            draw_id    INTEGER PRIMARY KEY,
            draw_date  TEXT NOT NULL UNIQUE,
            numbers    TEXT NOT NULL,
            bonus      INTEGER CHECK (bonus BETWEEN 1 AND 40),
            powerball  INTEGER CHECK (powerball BETWEEN 1 AND 10)
        )
    """)
    conn.commit()

    imported = 0
    skipped = 0

    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("No headers found in CSV.")
            conn.close()
            return 0

        headers = list(reader.fieldnames)

        # Auto-detect
        if auto or not (date_col and numbers_col):
            mapping = _auto_detect_columns(headers)
            date_col = date_col or mapping.get("date")
            numbers_col = numbers_col or mapping.get("numbers")
            bonus_col = bonus_col or mapping.get("bonus")
            pb_col = pb_col or mapping.get("powerball")

        if not date_col or not numbers_col:
            print("Could not identify date and numbers columns.")
            print(f"Headers: {headers}")
            print("Try: --date-col NAME --numbers-col NAME")
            conn.close()
            return 0

        print(f"Columns: date={date_col}, numbers={numbers_col}, bonus={bonus_col}, pb={pb_col}")

        for row_num, row in enumerate(reader, 2):
            try:
                date_raw = row.get(date_col, "").strip()
                if not date_raw:
                    skipped += 1
                    continue

                # Parse date
                date_iso = date_raw
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d"):
                    try:
                        date_iso = datetime.strptime(date_raw, fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue

                # Parse numbers
                nums_raw = row.get(numbers_col, "")
                numbers = _parse_numbers(nums_raw)
                if len(numbers) != 6:
                    skipped += 1
                    continue

                bonus = 0
                if bonus_col:
                    with contextlib.suppress(ValueError, TypeError):
                        bonus = int(row.get(bonus_col, "0"))

                powerball = 0
                if pb_col:
                    with contextlib.suppress(ValueError, TypeError):
                        powerball = int(row.get(pb_col, "0"))

                nums_str = ",".join(str(n) for n in numbers)

                cur = conn.execute("SELECT COALESCE(MAX(draw_id), 0) FROM draws")
                new_id = cur.fetchone()[0] + 1
                conn.execute(
                    "INSERT INTO draws (draw_id, draw_date, numbers, bonus, powerball) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (new_id, date_iso, nums_str, bonus, powerball),
                )
                conn.commit()
                imported += 1

            except sqlite3.IntegrityError:
                skipped += 1
            except (ValueError, KeyError) as e:
                print(f"  Row {row_num}: {e}")
                skipped += 1

    conn.close()
    print(f"Imported: {imported}, Skipped: {skipped}")
    return imported


def import_csv_draws(
    file_path: str,
    mapping: dict[str, str],
    delimiter: str = ",",
) -> int:
    """Import draws from a CSV file using a column-mapping dict.

    Parameters
    ----------
    file_path : str
        Path to the CSV file.
    mapping : dict
        Maps CSV column names to DB fields, e.g.:
        {'Date': 'draw_date', 'Numbers': 'numbers', 'Bonus': 'bonus', 'Powerball': 'powerball'}
        Recognised DB fields: draw_date, numbers, bonus, powerball.
    delimiter : str
        CSV delimiter (default ',').

    Returns
    -------
    int
        Number of rows inserted.
    """
    # Convert mapping to the format expected by import_csv
    date_col = mapping.get("draw_date")
    numbers_col = mapping.get("numbers")
    bonus_col = mapping.get("bonus")
    powerball_col = mapping.get("powerball")

    # If using the mapping dict, the keys are CSV column names
    # so we invert: find which CSV column maps to each DB field
    inv = {v: k for k, v in mapping.items()}
    date_col = inv.get("draw_date", date_col)
    numbers_col = inv.get("numbers", numbers_col)
    bonus_col = inv.get("bonus", bonus_col)
    powerball_col = inv.get("powerball", powerball_col)

    return import_csv(
        filepath=file_path,
        date_col=date_col,
        numbers_col=numbers_col,
        bonus_col=bonus_col,
        pb_col=powerball_col,
        auto=False,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Import lottery draws from CSV.")
    parser.add_argument("file", help="CSV file to import")
    parser.add_argument("--date-col", help="Date column name")
    parser.add_argument("--numbers-col", help="Numbers column name")
    parser.add_argument("--bonus-col", help="Bonus ball column name")
    parser.add_argument("--pb-col", help="Powerball column name")
    parser.add_argument("--auto", action="store_true", help="Auto-detect columns")
    args = parser.parse_args()

    import_csv(
        args.file,
        date_col=args.date_col,
        numbers_col=args.numbers_col,
        bonus_col=args.bonus_col,
        pb_col=args.pb_col,
        auto=args.auto,
    )


if __name__ == "__main__":
    main()
