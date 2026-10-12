#!/usr/bin/env python3
"""Binary search to find the first valid draw number."""

import requests

API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}


def exists(n: int) -> bool:
    r = requests.get(f"{API_BASE}/{n}", headers=headers, timeout=10)
    return r.status_code == 200


low, high = 1, 2615
first_valid = None

print("Binary searching for first valid draw number...")
while low <= high:
    mid = (low + high) // 2
    if exists(mid):
        first_valid = mid
        high = mid - 1
        print(f"  #{mid} EXISTS → searching lower")
    else:
        low = mid + 1
        print(f"  #{mid} MISSING → searching higher")

if first_valid:
    print(f"\nFirst valid draw number: {first_valid}")
    for n in [first_valid - 1, first_valid, first_valid + 1]:
        r = requests.get(f"{API_BASE}/{n}", headers=headers, timeout=10)
        status = "EXISTS" if r.status_code == 200 else "MISSING"
        print(f"  #{n}: {status}")
else:
    print("No valid draws found in range 1-2615")