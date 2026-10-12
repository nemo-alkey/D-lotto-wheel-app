#!/usr/bin/env python3
"""Test the correct API endpoint."""

import requests
import json

BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

print("Testing correct endpoint:", BASE)
print("=" * 60)

r = requests.get(BASE, headers=headers, timeout=15)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type', 'unknown')}")
print(f"Content-Length: {len(r.text)}")
print()

if r.status_code == 200:
    try:
        data = r.json()
        print(f"Type: {type(data)}")
        if isinstance(data, list):
            print(f"List length: {len(data)}")
            if data:
                print(f"\nFirst item keys: {list(data[0].keys())}")
                print(f"First item: {json.dumps(data[0], indent=2)}")
                print(f"\nLast item: {json.dumps(data[-1], indent=2)}")
        elif isinstance(data, dict):
            print(f"Dict keys: {list(data.keys())}")
            print(json.dumps(data, indent=2)[:1000])
    except Exception as e:
        print(f"JSON parse error: {e}")
        print(f"Raw text (first 500 chars): {r.text[:500]}")