#!/usr/bin/env python3
"""Find API endpoints in page JavaScript."""

import requests
import re

url = "https://mylotto.co.nz/results/lotto/archive"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

r = requests.get(url, headers=headers, timeout=15)
text = r.text

print("Searching for API endpoints in page source...")
print("=" * 60)

# Find all URLs
urls = re.findall(r'https?://[^\s"\'<>]+', text)
api_urls = [u for u in urls if "api" in u.lower() or "results" in u.lower() or "draw" in u.lower()]
print(f"\nAPI/Results URLs found ({len(api_urls)}):")
for u in set(api_urls):
    print(f"  {u}")

# Find fetch/XHR calls
fetch_calls = re.findall(r'fetch\(["\']([^"\']+)["\']', text)
print(f"\nFetch calls ({len(fetch_calls)}):")
for c in set(fetch_calls):
    print(f"  {c}")

# Find axios or other HTTP client calls
axios_calls = re.findall(r'axios\.[a-z]+\(["\']([^"\']+)["\']', text)
print(f"\nAxios calls ({len(axios_calls)}):")
for c in set(axios_calls):
    print(f"  {c}")

# Find any .json() or data URLs
json_urls = re.findall(r'["\']([^"\']+\.json)["\']', text)
print(f"\nJSON file references ({len(json_urls)}):")
for j in set(json_urls):
    print(f"  {j}")

# Look for window.__INITIAL_STATE__ or similar
state_patterns = [
    r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
    r'window\.__DATA__\s*=\s*(\{.*?\});',
    r'window\.__APP_DATA__\s*=\s*(\{.*?\});',
]
for pattern in state_patterns:
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        print(f"\nFound initial state data! ({len(matches[0])} chars)")
        print(matches[0][:500])

# Check existing selenium_scraper.py
print("\n" + "=" * 60)
print("Checking existing selenium_scraper.py...")
try:
    with open("selenium_scraper.py", "r", encoding="utf-8") as f:
        content = f.read()
    print(f"File length: {len(content)} chars")
    
    # Show first 50 lines
    lines = content.split("\n")[:50]
    print("\nFirst 50 lines:")
    for i, line in enumerate(lines, 1):
        print(f"{i:3}: {line}")
except Exception as e:
    print(f"Could not read: {e}")