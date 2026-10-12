import requests
from datetime import date, timedelta

url = "https://mylotto.co.nz/api/results/lotto"

for year in [2025, 2020, 2015, 2010, 2005, 2000, 1995, 1990, 1987]:
    d = date(year, 6, 15)
    while d.weekday() not in [2, 5]:  # Wed=2, Sat=5
        d += timedelta(days=1)
    
    r = requests.get(f"{url}/{d.isoformat()}", headers={"Accept": "application/json"}, timeout=10)
    print(f"{d} -> {r.status_code}")
    
    if r.status_code == 200:
        data = r.json().get("result", {})
        balls = data.get("mainBalls")
        draw_num = data.get("drawNumber")
        print(f"  Draw #{draw_num}: {balls}")