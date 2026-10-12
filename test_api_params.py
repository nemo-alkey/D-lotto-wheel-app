#!/usr/bin/env python3
"""Test API parameters for historical draw access."""

import requests

BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

print("Testing API parameter variations")
print("=" * 60)

# Test 1: drawNumber parameter
print("\n1. drawNumber=1 (first ever draw)")
r = requests.get(BASE, params={"drawNumber": 1}, headers=headers, timeout=10)
print(f"   Status: {r.status_code}")
if r.status_code == 200:
    try:
        data = r.json()
        lotto = data.get("lotto", {})
        print(f"   Draw: #{lotto.get('drawNumber')} on {lotto.get('drawDate')}")
        nums = lotto.get("lottoWinningNumbers", {}).get("numbers", [])
        print(f"   Numbers: {nums}")
    except:
        print(f"   Response: {r.text[:200]}")

# Test 2: drawNumber=2614 (previous draw)
print("\n2. drawNumber=2614 (previous draw)")
r = requests.get(BASE, params={"drawNumber": 2614}, headers=headers, timeout=10)
print(f"   Status: {r.status_code}")
if r.status_code == 200:
    try:
        data = r.json()
        lotto = data.get("lotto", {})
        print(f"   Draw: #{lotto.get('drawNumber')} on {lotto.get('drawDate')}")
        nums = lotto.get("lottoWinningNumbers", {}).get("numbers", [])
        print(f"   Numbers: {nums}")
    except:
        print(f"   Response: {r.text[:200]}")

# Test 3: date parameter
print("\n3. date=2026-08-23 (previous draw date)")
r = requests.get(BASE, params={"date": "2026-08-23"}, headers=headers, timeout=10)
print(f"   Status: {r.status_code}")
if r.status_code == 200:
    try:
        data = r.json()
        lotto = data.get("lotto", {})
        print(f"   Draw: #{lotto.get('drawNumber')} on {lotto.get('drawDate')}")
    except:
        print(f"   Response: {r.text[:200]}")

# Test 4: page parameter
print("\n4. page=2")
r = requests.get(BASE, params={"page": 2}, headers=headers, timeout=10)
print(f"   Status: {r.status_code}")

# Test 5: Check HTML archive page
print("\n5. HTML archive pages")
archive_urls = [
    "https://mylotto.co.nz/results/lotto/archive",
    "https://mylotto.co.nz/results/lotto/history",
]
for url in archive_urls:
    r = requests.get(url, headers=headers, timeout=10)
    print(f"   {url} -> {r.status_code} ({r.headers.get('content-type', 'unknown')})")

# Test 6: Bulk endpoints
print("\n6. Bulk/history endpoints")
bulk_urls = [
    "https://pathway.mylotto.co.nz/api/results/v1/results/lotto/history",
    "https://pathway.mylotto.co.nz/api/results/v1/history/lotto",
]
for url in bulk_urls:
    r = requests.get(url, headers=headers, timeout=10)
    print(f"   {url} -> {r.status_code}")