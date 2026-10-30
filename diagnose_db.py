#!/usr/bin/env python3
"""Diagnose database file location and contents."""

import os
import sqlite3
from pathlib import Path

possible_paths = [
    Path("data/lotto.db").resolve(),
    Path("lotto.db").resolve(),
    Path("../data/lotto.db").resolve(),
]

print("Current working directory:", Path.cwd())
print()

for p in possible_paths:
    print(f"Checking: {p}")
    print(f"  Exists: {p.exists()}")
    if p.exists():
        print(f"  Size: {p.stat().st_size} bytes")
        try:
            conn = sqlite3.connect(str(p), timeout=5)
            tables = [
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ]
            print(f"  Tables: {tables}")
            if "draws" in tables:
                count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
                print(f"  draws rows: {count}")
                if count > 0:
                    for row in conn.execute("SELECT * FROM draws LIMIT 2"):
                        print(f"    {row}")
            conn.close()
        except Exception as e:
            print(f"  Error: {e}")
    print()

print("All .db files in project:")
for root, _dirs, files in os.walk("."):
    for f in files:
        if f.endswith(".db"):
            fp = Path(root) / f
            print(f"  {fp.resolve()} ({fp.stat().st_size} bytes)")
