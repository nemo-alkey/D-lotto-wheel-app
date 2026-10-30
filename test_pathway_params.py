#!/usr/bin/env python3
"""Test pathway API with pagination/limit parameters."""

import json

import requests

BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

params_to_test = [
    {"page": 1, "size": 100},
    {"page": 0, "size": 100},
    {"offset": 0, "limit": 100},
    {"limit": 100},
    {"history": "true"},
    {"all": "true"},
    {"from": "1987-01-01", "to": "2026-12-31"},
    {"startDate": "1987-01-01", "endDate": "2026-12-31"},
]

print("Testing pathway API with various parameters...")
print("=" * 60)

for params in params_to_test:
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}?{param_str}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        ct = r.headers.get("content-type", "unknown")
        print(f"\n{param_str}")
        print(f"  Status: {r.status_code} | Type: {ct}")

        if r.status_code == 200 and "json" in ct:
            data = r.json()
            if isinstance(data, list):
                print(f"  LIST: {len(data)} items")
                if data:
                    print(f"  First: {json.dumps(data[0], indent=2)[:300]}")
            elif isinstance(data, dict):
                lotto = data.get("lotto", {})
                dn = lotto.get("drawNumber")
                dd = lotto.get("drawDate")
                print(f"  SINGLE: Draw #{dn} on {dd}")
                other_keys = [k for k in data if k != "lotto"]
                if other_keys:
                    print(f"  Other keys: {other_keys}")
    except Exception as e:
        print(f"\n{param_str}")
        print(f"  ERROR: {e}")
