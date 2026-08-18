# Troubleshooting

Common errors and how to fix them, organized by symptom. If your problem isn't
listed here, skip to [Collecting diagnostics](#collecting-diagnostics).

## Startup & configuration

### `Configuration error — refusing to start` (exit code 1)

**Cause:** `config_manager.validate_startup()` fails fast on insecure
production config: with `DEBUG=false`, a placeholder/empty `SECRET_KEY` or a
wildcard (`*`) in `CORS_ORIGINS` is fatal. The related message `Configuration
error — invalid environment settings` means an env var has the wrong type; the
offending fields are printed one per line.

**Fix:** copy `.env.example` to `.env`, then generate a real secret and set it:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# SECRET_KEY=<output> in .env (legacy alias JWT_SECRET_KEY also works)
```

Replace any `*` in `CORS_ORIGINS` with explicit origins, e.g.
`CORS_ORIGINS=http://localhost:5173`. For local development only, `DEBUG=true`
relaxes these checks (the Docker dev override sets it automatically — see
[Docker](#docker)).

## API errors

### 401 / 403 on `/draws` or `/me`

**Cause:** `POST /draws` requires a Bearer token from an **admin** user.
Missing/invalid/expired token → 401; valid non-admin token → 403 ("Admin
privileges required."). Access tokens expire after 15 minutes.

**Fix:** get a token and pass it in the `Authorization` header:

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'

curl -X POST http://localhost:8000/draws \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" -d '{...}'
```

Expired access token? Exchange the refresh token (valid 7 days) at
`POST /token/refresh`. No admin yet? Create one:

```bash
JWT_ADMIN_PASSWORD='YourStrongPass1' make seed-admin   # or: python create_admin.py
```

(Passwords need 8+ chars with upper, lower, and a digit.)

### 423 — account locked

**Cause:** 5 failed logins within 30 minutes lock the account (in-memory
lockout in `auth.py`; attempts logged to `data/logs/security.log`).

**Fix:** wait 30 minutes, or restart the API — the lockout table is in memory,
so a restart clears it. If the failures weren't you, check
`data/logs/security.log` for the source IPs.

### 429 — rate limit exceeded

**Cause:** per-IP limits: anonymous 10/min, authenticated 60/min, heavy
endpoints (`/ev_simulation`, `/backtest/bonus_impact`) 5/min, login/refresh
5/min per IP.

**Fix:** honor the `Retry-After` header (also in the body as
`retry_after_seconds`), authenticate to raise 10/min → 60/min, and cache
instead of polling. In development you can set `RATE_LIMIT_ENABLED=false` in
`.env`.

### 501 — "ML predictions require a trained model"

**Cause:** `POST /predictions` with `method="ml"` needs `model.pkl` in the repo
root.

**Fix:** run `python train_ml_model.py`, or use `method="frequency"` /
`method="ensemble"`, which need no model file.

### 404 — "No draw data found."

**Cause:** the draws table is empty (fresh install, or the pipeline never ran).

**Fix:** seed the database:

```bash
python migrate.py upgrade   # ensure schema exists first
make seed-db                # = python update_draws.py
```

For a specific window: `python update_draws.py --date 2026-08-01` or
`--range 2026-07-01:2026-08-01`.

## Health & monitoring

### `/health` reports "degraded"

`/health` returns 200 with `"status": "degraded"` when a non-critical check
warns — read the per-check payload:

- **redis: fail** — safe short-term: the API falls back to in-memory
  caching/rate limiting. Start Redis to clear it.
- **backup: warn** — no backup in `backups/` or newest is older than 48 h. Run
  `python database_backup.py backup --now`, or schedule with
  `python database_backup.py daemon`.
- **draw stale** — latest draw older than 72 h. Run `python update_draws.py`.
- **503 "unhealthy"** means a critical check failed (database unreachable, disk
  unreadable) — check `DATABASE_URL` and disk space.

### Prometheus / Grafana can't reach the API

**Cause:** `monitoring/prometheus.yml` scrapes `host.docker.internal:8000` —
it expects the API on the **host** (`uvicorn api:app --port 8000`), not in
another container. `docker-compose.monitoring.yml` includes
`extra_hosts: host.docker.internal:host-gateway` so this works on Linux too.

**Fix:** start the API on the host before bringing up the monitoring stack and
verify `curl http://localhost:8000/metrics` from the host. If the API runs in
the main `docker-compose.yml` stack instead, point the scrape target at that
service (e.g. `app:8000`) on a shared network.

## Alerts

### Email alerts not sending

**Cause:** SMTP credentials missing/wrong in `.env` (`SMTP_SERVER`,
`SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`; canonical
`SMTP_HOST`/`SMTP_USER`/`SMTP_PASS` aliases also work).

**Fix:** Gmail rejects normal passwords — use an **app password** (Google
Account → Security → 2-Step Verification → App passwords). Every send attempt
is logged to `alert.log` (repo root, override with `ALERT_LOG`) — look for SMTP
errors such as `535 Username and Password not accepted`.

### Webhook alerts not firing

**Cause:** `ALERT_WEBHOOK_URL` unset or malformed. It must be a full Discord or
Slack incoming-webhook URL (`https://discord.com/api/webhooks/...` or
`https://hooks.slack.com/services/...`); the payload sends both `content`
(Discord) and `text` (Slack) keys.

**Fix:** set the URL in `.env` and restart. Alerts only dispatch on **state
transitions** (ok → firing), persisted in `data/logs/alert_state.json` — an
already-firing check won't re-notify. Evaluate rules manually with
`python -m monitoring.alerting`.

## Data pipeline

### Selenium / ChromeDriver errors

**Fix:** run the built-in readiness check — it verifies the driver starts and
prints configuration guidance without scraping:

```bash
python update_draws.py --check-selenium
```

Selenium is only a fallback: the pipeline tries the MyLotto API first (with
retry/backoff), then HTML parsing. Force the Selenium path with
`--use-selenium` only if the primary sources fail.

## Database

### Alembic migration errors on a pre-existing database

**Cause:** the DB predates migrations, so Alembic tries to create tables that
already exist.

**Fix:** stamp the baseline, then upgrade:

```bash
python migrate.py stamp 001
python migrate.py upgrade
python migrate.py current   # verify; `check` warns if behind latest
```

Fresh installs just need `python migrate.py upgrade`.

### Backup problems

`database_backup.py` CLI: `backup [--now]`, `restore <file> [--target]`,
`list [--days N]`, `verify <file>`, `daemon`. Backups land in `backups/`, are
gzipped after 7 days, and pruned after `BACKUP_RETENTION_DAYS` (default 30).
Activity and failures go to `data/logs/backup.log`; always `verify` a file
before relying on `restore`.

## Mobile frontend

### CORS errors from the mobile app

**Cause:** the API only allows origins in `CORS_ORIGINS` — never `*`. The Vite
dev server origin must be listed explicitly, and `localhost` and `127.0.0.1`
are different origins.

**Fix:** add the origin you actually use to `.env` and restart the API:
`CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`. The production
build served at `/mobile` by the API itself is same-origin and needs no entry.

## Ports & processes

### Port already in use (8000 / 8501 / 8080)

**Fix:** find and stop the process holding the port, or pick another port.

```bash
# Git Bash (PowerShell: Get-NetTCPConnection -LocalPort 8000)
netstat -ano | grep :8000
taskkill //PID <PID> //F        # PowerShell: Stop-Process -Id <PID>
```

Alternatives: `uvicorn api:app --port 8001`,
`streamlit run dashboard.py --server.port 8502`. Port 8080 is the nginx
reverse proxy in `docker-compose.yml` — edit its `ports:` mapping on a clash.

## Docker

### Volume permission errors (container user `lotto`)

**Cause:** the image runs as non-root user `lotto` (uid 1000); bind-mounted
host dirs (`data/`, `backups/`, `exports/`) owned by another uid aren't
writable.

**Fix:** on a Linux host, `sudo chown -R 1000:1000 data backups exports`. On
Docker Desktop (Windows/macOS) the file-sharing layer handles this — if you
still hit it, recreate the containers.

### Override file confusion (DEBUG=true in "production" runs)

**Cause:** `docker-compose.override.yml` is **auto-loaded** by
`docker compose up` and sets `DEBUG=true` plus hot-reload mounts.

**Fix:** bypass the override for a production-like run:

```bash
docker compose -f docker-compose.yml up --build
```

Migrations run at container boot via `scripts/docker-entrypoint.sh`;
supervisord runs FastAPI + Streamlit in one container — see
`docker compose logs -f`.

## Windows-specific

- **`Activate.ps1 cannot be loaded` (execution policy):** run
  `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once
  in PowerShell, then `venv\Scripts\Activate.ps1`. In Git Bash use
  `source venv/Scripts/activate` — no policy change needed.
- **`make: command not found`:** install Make via `winget` (see the README), or
  run the underlying commands shown in the `Makefile` directly.
- **Paths:** use forward slashes or quoted backslashes in shell commands; `.env`
  values should be plain paths without surrounding quotes.

## Collecting diagnostics

Before reporting an issue, gather:

- `data/logs/app.log` — one JSON object per request, with request ids.
- `data/logs/security.log` — auth failures, lockouts, admin actions.
- `data/logs/backup.log` — backup/restore activity.
- `alert.log` — email/SMS alert send attempts.
- `curl http://localhost:8000/health` — per-check status.
- `curl http://localhost:8000/metrics` — Prometheus counters/gauges.
- `python migrate.py current` / `python migrate.py check` — schema state.

The interactive API docs at `/docs` (and `/docs/custom`, `/redoc`) show the
exact request/response schemas and documented error codes per endpoint — often
the fastest way to compare expected vs. actual behavior.
