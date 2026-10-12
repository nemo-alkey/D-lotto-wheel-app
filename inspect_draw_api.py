#!/usr/bin/env python3
"""Print the full JSON for a few draws to see if prize payout details are included."""

import json
import requests

API_BASE = "https://pathway.mylotto.co.nz/api/results/v1/results/lotto"
headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# Test a recent draw and an older draw (if available)
draws_to_test = [2615, 2614, 2512, 2000]

for draw_num in draws_to_test:
    url = f"{API_BASE}/{draw_num}"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 200:
        data = r.json()
        print(f"\n{'='*60}\nDraw #{draw_num}\n{'='*60}")
        # Print top-level keys first
        print("Top-level keys:", list(data.keys()))
        # Print lotto section (which likely has prize info)
        if "lotto" in data:
            print("\nlotto keys:", list(data["lotto"].keys()))
            # Pretty print the whole lotto section, but maybe truncate if huge
            lotto_str = json.dumps(data["lotto"], indent=2)
            print(lotto_str[:3000])   # print first 3000 chars
        # Check if there is a separate 'prizes' or 'divisions' section
        for key in data:
            if "prize" in key.lower() or "division" in key.lower() or "winner" in key.lower():
                print(f"\nFound section: {key}")
                print(json.dumps(data[key], indent=2)[:2000])
    else:
        print(f"Draw {draw_num} -> HTTP {r.status_code}")