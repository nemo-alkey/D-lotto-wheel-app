#!/usr/bin/env python3
"""Diagnose which endpoint actually returns draw data."""

import requests
from datetime import date

# Test multiple possible endpoints
test_date = "2026-08-20"
endpoints = [
    f"https://mylotto.co.nz/api/results/lotto/{test_date}",
    f"https://pathway.mylotto.co.nz/api/results/lotto/{test_date}",
    f"https://pathway.mylotto.co.nz/results/lotto/{test_date}",
    "https://mylotto.co.nz/results/lotto",
    "https://pathway.mylotto.co.nz/results/lotto",
]

headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

print("Testing endpoints for", test_date)
print("=" * 60)

for url in endpoints:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        content_type = r.headers.get("content-type", "unknown")
        print(f"\nURL: {url}")
        print(f"Status: {r.status_code} | Content-Type: {content_type}")
        
        if r.status_code == 200:
            text = r.text.strip()
            if text.startswith("{"):
                print(f"JSON: {text[:300]}")
            elif text.startswith("<"):
                print(f"HTML (first 150 chars): {text[:150]}")
            else:
                print(f"Text (first 150 chars): {text[:150]}")
    except Exception as e:
        print(f"\nURL: {url}")
        print(f"ERROR: {e}")

# Also inspect update_draws.py for its actual URL pattern
print("\n" + "=" * 60)
print("Checking update_draws.py for its fetch logic...")
try:
    with open("update_draws.py", "r", encoding="utf-8") as f:
        content = f.read()
    
    import re
    urls = re.findall(r'https?://[^\s"\'<>]+', content)
    print("URLs found in update_draws.py:")
    for u in urls[:10]:
        print(f"  {u}")
    
    base_match = re.search(r'API_BASE\s*=\s*["\']([^"\']+)["\']', content)
    if base_match:
        print(f"\nAPI_BASE = {base_match.group(1)}")
    
    func_match = re.search(r'def\s+\w*fetch\w*\([^)]*\):', content)
    if func_match:
        idx = content.find(func_match.group(0))
        print(f"\nFetch function found around line {content[:idx].count(chr(10)) + 1}")
        snippet = content[idx:content.find("\ndef ", idx+1) if content.find("\ndef ", idx+1) > 0 else idx+1500]
        print(snippet[:1500])
except Exception as e:
    print(f"Could not read update_draws.py: {e}")