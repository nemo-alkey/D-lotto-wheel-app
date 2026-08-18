"""Smoke-test the new v2 endpoints against a COPY of lotto.db (temp cwd)."""

import os
import shutil
import sqlite3
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="lottosmoke_")
shutil.copy("lotto.db", os.path.join(tmp, "lotto.db"))
os.chdir(tmp)
sys.path.insert(0, r"D:\lotto-wheel-app")

import auth  # noqa: E402

auth.DB_PATH = os.path.join(tmp, "lotto.db")

from fastapi.testclient import TestClient  # noqa: E402

from api import app  # noqa: E402

results = []

with TestClient(app) as client:
    # reset rate limiter between groups
    def reset() -> None:
        try:
            api_reset = app.state.limiter.limiter.storage.reset
            api_reset()
        except Exception:
            pass

    # --- auth: register + make admin ---
    r = client.post("/register", json={"username": "smokeadmin", "password": "pass12345"})
    results.append(("register", r.status_code, r.status_code == 201))
    conn = sqlite3.connect(os.path.join(tmp, "lotto.db"))
    conn.execute("UPDATE users SET is_admin = 1 WHERE username = 'smokeadmin'")
    conn.commit()
    conn.close()
    r = client.post("/token", json={"username": "smokeadmin", "password": "pass12345"})
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    results.append(("token", r.status_code, r.status_code == 200))

    # --- POST /draws ---
    reset()
    r = client.post(
        "/draws",
        json={
            "draw_number": 900001,
            "date": "2099-01-01",
            "main_numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 7,
        },
    )
    results.append(
        ("POST /draws (no token) -> 401/403", r.status_code, r.status_code in (401, 403))
    )

    r = client.post(
        "/draws",
        headers=headers,
        json={
            "draw_number": 900001,
            "date": "2099-01-01",
            "main_numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 7,
        },
    )
    results.append(("POST /draws (admin) -> 201", r.status_code, r.status_code == 201))

    r = client.post(
        "/draws",
        headers=headers,
        json={
            "draw_number": 900002,
            "date": "2099-01-01",
            "main_numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 8,
        },
    )
    results.append(("POST /draws duplicate date -> 409", r.status_code, r.status_code == 409))

    r = client.post(
        "/draws",
        headers=headers,
        json={
            "draw_number": 0,
            "date": "2099-01-02",
            "main_numbers": [1, 2, 3, 4, 5],
            "bonus": 8,
        },
    )
    results.append(("POST /draws bad payload -> 422", r.status_code, r.status_code == 422))

    # --- POST /predictions ---
    reset()
    r = client.post("/predictions", headers=headers, json={"method": "frequency", "top_k": 10})
    ok = r.status_code == 200 and len(r.json()["numbers"]) == 10
    if ok:
        probs = r.json()["probabilities"]
        ok = all(0 <= p <= 1 for p in probs)
    results.append(("POST /predictions frequency -> 200, probs 0-1", r.status_code, ok))

    r = client.post("/predictions", headers=headers, json={"method": "ml", "top_k": 6})
    results.append(
        ("POST /predictions ml (no model.pkl) -> 501", r.status_code, r.status_code == 501)
    )

    r = client.post("/predictions", headers=headers, json={"method": "bogus", "top_k": 6})
    results.append(("POST /predictions bogus method -> 422", r.status_code, r.status_code == 422))

    # --- POST /wheels/generate ---
    reset()
    r = client.post(
        "/wheels/generate",
        headers=headers,
        json={
            "pool_size": 10,
            "guarantee_type": "4 if 4",
            "user_numbers": [1, 3, 7, 11, 19, 22, 27, 33, 35, 40],
        },
    )
    body = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and len(body.get("tickets", [])) > 0
    if ok:
        cs = body["coverage_stats"]
        ok = "pair_coverage_pct" in cs and "ticket_count" in cs
    results.append(("POST /wheels/generate -> 200 with tickets", r.status_code, ok))

    r = client.post(
        "/wheels/generate",
        headers=headers,
        json={
            "pool_size": 10,
            "guarantee_type": "bogus guarantee",
        },
    )
    results.append(
        ("POST /wheels/generate bad guarantee -> 400", r.status_code, r.status_code == 400)
    )

    r = client.post(
        "/wheels/generate",
        headers=headers,
        json={
            "pool_size": 20,
            "guarantee_type": "6 if 6",
            "user_numbers": list(range(1, 21)),
        },
    )
    results.append(
        ("POST /wheels/generate impossible -> 422/404", r.status_code, r.status_code in (404, 422))
    )

    # --- POST /backtest ---
    reset()
    first_wheel = next(iter(client.get("/wheels").json()["wheels"]))
    r = client.post(
        "/backtest",
        headers=headers,
        json={
            "wheel_type": first_wheel,
            "ticket_count": 5,
        },
    )
    body = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and "roi_pct" in body and "division_breakdown" in body
    results.append(("POST /backtest (all draws) -> 200", r.status_code, ok))

    r = client.post(
        "/backtest",
        headers=headers,
        json={
            "wheel_type": first_wheel,
            "start_date": "2000-01-01",
            "end_date": "2099-12-31",
        },
    )
    results.append(("POST /backtest date window -> 200", r.status_code, r.status_code == 200))

    r = client.post(
        "/backtest",
        headers=headers,
        json={
            "wheel_type": "no-such-wheel",
        },
    )
    results.append(("POST /backtest bad wheel -> 404", r.status_code, r.status_code == 404))

    r = client.post(
        "/backtest",
        headers=headers,
        json={
            "wheel_type": first_wheel,
            "start_date": "2099-01-01",
            "end_date": "2000-01-01",
        },
    )
    results.append(("POST /backtest inverted dates -> 400", r.status_code, r.status_code == 400))

    # --- GET /docs/custom ---
    r = client.get("/docs/custom")
    ok = r.status_code == 200 and "redoc" in r.text.lower()
    results.append(("GET /docs/custom -> 200 redoc HTML", r.status_code, ok))

    # --- regression spot checks ---
    reset()
    r = client.get("/")
    results.append(("GET / regression", r.status_code, r.status_code == 200))
    r = client.get("/wheels")
    results.append(("GET /wheels regression", r.status_code, r.status_code == 200))

print()
failed = 0
for name, code, ok in results:
    print(f"  [{'OK' if ok else 'FAIL'}] {name} (got {code})")
    failed += 0 if ok else 1
print(f"\n{len(results) - failed}/{len(results)} smoke checks passed")
sys.exit(1 if failed else 0)
