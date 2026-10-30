#!/usr/bin/env python3
"""Test draw number in URL path."""

import requests

headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

urls = [
    "https://pathway.mylotto.co.nz/api/results/v1/results/lotto/1",
    "https://pathway.mylotto.co.nz/api/results/v1/results/lotto/2615",
    "https://pathway.mylotto.co.nz/api/results/v1/results/lotto/2614",
    "https://pathway.mylotto.co.nz/api/results/v1/lotto/2615",
    "https://pathway.mylotto.co.nz/api/results/v1/draw/2615",
]

print("Testing draw number in URL path...")
print("=" * 60)

for url in urls:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        ct = r.headers.get("content-type", "unknown")
        print(f"\n{url}")
        print(f"  Status: {r.status_code} | Type: {ct}")
        if r.status_code == 200 and "json" in ct:
            data = r.json()
            lotto = data.get("lotto", {})
            print(f"  Draw #{lotto.get('drawNumber')} on {lotto.get('drawDate')}")
    except Exception as e:
        print(f"\n{url}")
        print(f"  ERROR: {e}")
