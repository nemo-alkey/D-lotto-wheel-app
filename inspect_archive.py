#!/usr/bin/env python3
"""Inspect HTML archive page structure."""

import requests
from bs4 import BeautifulSoup

url = "https://mylotto.co.nz/results/lotto/archive"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

print(f"Fetching: {url}")
r = requests.get(url, headers=headers, timeout=15)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"Length: {len(r.text)} chars")
print()

soup = BeautifulSoup(r.text, "html.parser")

# Look for tables
print("Tables found:", len(soup.find_all("table")))
for i, table in enumerate(soup.find_all("table")[:3]):
    print(f"\nTable {i}:")
    rows = table.find_all("tr")[:5]
    for row in rows:
        cells = row.find_all(["td", "th"])
        print(f"  {len(cells)} cells: {[c.get_text(strip=True)[:50] for c in cells]}")

# Look for draw-related divs/classes
print("\n" + "=" * 60)
print("Looking for draw data in page...")

draw_divs = soup.find_all(class_=lambda x: x and any(w in str(x).lower() for w in ["draw", "result", "number", "win"]))[:10]
print(f"Found {len(draw_divs)} elements with draw/result/number/win in class")
for div in draw_divs[:3]:
    print(f"  class={div.get('class')} | text={div.get_text(strip=True)[:100]}")

# Look for script tags with JSON data
scripts = soup.find_all("script")
print(f"\nScript tags: {len(scripts)}")
for script in scripts:
    text = script.string or ""
    if "draw" in text.lower() and len(text) > 500:
        print(f"\nScript with draw data ({len(text)} chars):")
        print(text[:500])
        break

# Look for pagination
pagination = soup.find_all(class_=lambda x: x and "page" in str(x).lower())
print(f"\nPagination elements: {len(pagination)}")
for p in pagination[:5]:
    print(f"  {p.get_text(strip=True)[:50]}")

# Look for links to specific draws
links = soup.find_all("a", href=True)
draw_links = [a for a in links if any(w in a["href"].lower() for w in ["draw", "result", "lotto"])][:10]
print(f"\nDraw-related links: {len(draw_links)}")
for a in draw_links[:5]:
    print(f"  {a['href']} -> {a.get_text(strip=True)[:50]}")