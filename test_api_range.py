import requests
from datetime import date, timedelta

url = "https://mylotto.co.nz/api/results/lotto"

for year in [2025, 2020, 2015, 2010, 2005, 2000, 1995, 1990, 1987]:
    d = date(year, 6, 15)
    while d.weekday() not in [2, 5]:
        d += timedelta(days=1)
    
    r = requests.get(f"{url}/{d.isoformat()}", headers={"Accept": "application/json"}, timeout=10)
    print(f"{d} -> {r.status_code} | content-type: {r.headers.get('content-type', 'unknown')}")
    
    if r.status_code == 200:
        text = r.text.strip()
        if not text:
            print("  (empty body)")
            continue
        if text.startswith("<"):
            print(f"  (HTML response, first 100 chars: {text[:100]})")
            continue
        try:
            data = r.json().get("result", {})
            balls = data.get("mainBalls")
            draw_num = data.get("drawNumber")
            print(f"  Draw #{draw_num}: {balls}")
        except Exception as e:
            print(f"  JSON error: {e}")
            print(f"  Body preview: {text[:200]}")