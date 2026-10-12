#!/usr/bin/env python3
"""Test the promising draw endpoints found in the JS bundle."""

import requests
import json

headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

endpoints = [
    "https://mylotto.co.nz/api/draws/lotto",
    "https://mylotto.co.nz/api/draws/lotto/history",
    "https://mylotto.co.nz/api/draws/lotto/all",
    "https://mylotto.co.nz/api/draws/lotto/results",
    "https://mylotto.co.nz/api/draws/lotto/archive",
    "https://mylotto.co.nz/api/draws",
    "https://mylotto.co.nz/api/draws/powerball",
    "https://mylotto.co.nz/api/results/draws",
    "https://mylotto.co.nz/api/results/lotto/draws",
]

print("Testing promising endpoints from JS bundle...")
print("=" * 60)

for url in endpoints:
    try:
        r = requests.get(url, headers=headers, timeout=15)
        ct = r.headers.get("content-type", "unknown")
        print(f"\n{url}")
        print(f"  Status: {r.status_code} | Content-Type: {ct}")
        
        if r.status_code == 200:
            if "json" in ct:
                try:
                    data = r.json()
                    print(f"  Type: {type(data)}")
                    if isinstance(data, list):
                        print(f"  Items: {len(data)}")
                        if data:
                            print(f"  First: {json.dumps(data[0], indent=2)[:400]}")
                    elif isinstance(data, dict):
                        print(f"  Keys: {list(data.keys())[:10]}")
                        for k, v in data.items():
                            if isinstance(v, list):
                                print(f"  {k}: list[{len(v)}]")
                                if v:
                                    print(f"    First: {json.dumps(v[0], indent=2)[:300]}")
                                break
                except Exception as e:
                    print(f"  JSON error: {e}")
            else:
                print(f"  HTML (first 200 chars): {r.text[:200]}")
    except Exception as e:
        print(f"\n{url}")
        print(f"  ERROR: {e}")