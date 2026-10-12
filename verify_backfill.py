#!/usr/bin/env python3
"""Verify the backfill results."""

import sqlite3

conn = sqlite3.connect("data/lotto.db")

# Check total count
count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
print(f"Total draws: {count}")

# Check recent draws with draw_number populated
print("\nRecent draws with draw_number:")
rows = conn.execute("""
    SELECT draw_number, draw_date, numbers, bonus, powerball 
    FROM draws 
    WHERE draw_number IS NOT NULL 
    ORDER BY draw_number DESC 
    LIMIT 10
""").fetchall()
for row in rows:
    print(f"  #{row[0]} | {row[1]} | {row[2]} | B:{row[3]} | PB:{row[4]}")

# Check draws WITHOUT draw_number (older data)
print("\nDraws without draw_number (older data):")
no_num_count = conn.execute("SELECT COUNT(*) FROM draws WHERE draw_number IS NULL").fetchone()[0]
print(f"  Count: {no_num_count}")

if no_num_count > 0:
    rows = conn.execute("""
        SELECT draw_date, numbers, bonus, powerball 
        FROM draws 
        WHERE draw_number IS NULL 
        ORDER BY draw_date DESC 
        LIMIT 5
    """).fetchall()
    for row in rows:
        print(f"  {row[0]} | {row[1]} | B:{row[2]} | PB:{row[3]}")

# Date range
min_date, max_date = conn.execute("SELECT MIN(draw_date), MAX(draw_date) FROM draws").fetchone()
print(f"\nDate range: {min_date} to {max_date}")

conn.close()