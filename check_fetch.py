#!/usr/bin/env python3
"""Check how update_draws.py extracts draw numbers."""

with open("update_draws.py", encoding="utf-8") as f:
    content = f.read()

lines = content.split("\n")
for i, line in enumerate(lines, 1):
    if "drawNumber" in line or "draw_id" in line or "draw_number" in line:
        print(f"{i:3}: {line}")
