#!/usr/bin/env python3
"""Deep inspection: selenium scraper + JS bundles."""

import requests
import re

# 1. Show more of selenium_scraper.py
print("=" * 60)
print("SELENIUM SCRAPER - Lines 50-200")
print("=" * 60)
try:
    with open("selenium_scraper.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines[50:200], 51):
        print(f"{i:3}: {line.rstrip()}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 60)
print("SELENIUM SCRAPER - Lines 200-350")
print("=" * 60)
try:
    for i, line in enumerate(lines[200:350], 201):
        print(f"{i:3}: {line.rstrip()}")
except:
    pass

# 2. Check external JS bundles in archive page
print("\n" + "=" * 60)
print("EXTERNAL JS BUNDLES")
print("=" * 60)

url = "https://mylotto.co.nz/results/lotto/archive"
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)

script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', r.text)
print(f"\nScript sources found: {len(script_srcs)}")
for src in script_srcs:
    print(f"  {src}")

js_urls = [src for src in script_srcs if src.endswith(".js")]
print(f"\nJS files: {len(js_urls)}")

if js_urls:
    js_url = js_urls[0]
    if js_url.startswith("/"):
        js_url = "https://mylotto.co.nz" + js_url
    print(f"\nFetching JS bundle: {js_url}")
    js_r = requests.get(js_url, timeout=15)
    js_text = js_r.text
    print(f"Length: {len(js_text)} chars")
    
    api_patterns = [
        r'/api/[^\s"\'<>]+',
        r'https?://[^\s"\'<>]*api[^\s"\'<>]*',
        r'fetch\(["\']?(/[^"\']+)',
        r'url:\s*["\']([^"\']+)["\']',
        r'baseURL:\s*["\']([^"\']+)["\']',
    ]
    
    for pattern in api_patterns:
        matches = re.findall(pattern, js_text)
        if matches:
            print(f"\nPattern found {len(matches)} matches:")
            for m in set(matches[:10]):
                print(f"  {m}")

# 3. Try common SPA API patterns
print("\n" + "=" * 60)
print("TESTING COMMON SPA API PATTERNS")
print("=" * 60)

base = "https://mylotto.co.nz"
test_endpoints = [
    "/api/draws",
    "/api/draws/lotto",
    "/api/v1/draws",
    "/api/v2/draws",
    "/graphql",
    "/api/graphql",
    "/api/results/history",
    "/api/results/all",
    "/api/lotto/history",
    "/api/draw-results",
]

for endpoint in test_endpoints:
    full_url = base + endpoint
    try:
        resp = requests.get(full_url, headers={"Accept": "application/json"}, timeout=10)
        ct = resp.headers.get("content-type", "unknown")
        print(f"  {endpoint} -> {resp.status_code} ({ct})")
        if resp.status_code == 200 and "json" in ct:
            data = resp.json()
            if isinstance(data, list):
                print(f"    List with {len(data)} items")
            elif isinstance(data, dict):
                print(f"    Dict keys: {list(data.keys())[:5]}")
    except Exception as e:
        print(f"  {endpoint} -> ERROR: {e}")