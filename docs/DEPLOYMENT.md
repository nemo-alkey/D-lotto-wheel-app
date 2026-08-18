# Deployment Guide

Step-by-step deployment guides for the NZ Lotto Powerball platform. The stack
has two services: the FastAPI API (`api.py`, port 8000) and the Streamlit
dashboard (`dashboard.py`, port 8501). Persistent state is a SQLite database
(`lotto.db`) by default; PostgreSQL is supported via `DATABASE_URL`.

## 1. Local development

Prerequisites: Python 3.11+ (see `pyvenv.cfg` / CI matrix) and `make`
(optional; on Windows install via `winget install GnuWin32.Make` or use Git
Bash).

```bash
python -m venv venv
source venv/Scripts/activate        # Git Bash on Windows
# PowerShell:  .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                # PowerShell: copy .env.example .env
```

Edit `.env` and set at minimum `SECRET_KEY` (32+ random chars). Generate one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Initialize the database and load draw history:

```bash
python migrate.py upgrade           # fresh installs
# Pre-migration databases: python migrate.py stamp 001 && python migrate.py upgrade
python update_draws.py              # fetch latest draws (seed-db make target)
make seed-admin                     # requires JWT_ADMIN_PASSWORD env var
```

Windows note: prefix env vars inline only in Git Bash. In PowerShell set them
first, e.g. `$env:JWT_ADMIN_PASSWORD="s3cret"; python create_admin.py`.

Run both services (two terminals):

```bash
make run-api    # uvicorn api:app --host 0.0.0.0 --port 8000 --reload
make run-dash   # streamlit run dashboard.py --server.port 8501
```

- API docs: http://localhost:8000/docs (also `/redoc`, `/docs/custom`)
- Health probe: http://localhost:8000/health — Prometheus metrics at `/metrics`
- Dashboard: http://localhost:8501 (includes the "🔔 System Health" page)

## 2. Docker single-host

The `Dockerfile` is multi-stage: a builder stage compiles dependencies, the
runtime stage runs as the non-root user `lotto` (UID 1000) with `supervisord`
managing FastAPI + Streamlit in one container. `scripts/docker-entrypoint.sh`
runs at boot: it symlinks `/app/lotto.db` onto the `lotto-data` volume, runs
`python migrate.py upgrade` (logs a warning but still starts on failure), then
exec's supervisord so SIGTERM reaches both services.

```bash
docker compose up -d --build
```

Compose loads `docker-compose.yml` **plus `docker-compose.override.yml`
automatically** — the override enables dev mode (`DEBUG=true`, source bind-mount
with `--reload` hot reload). For a production-style run, skip the override:

```bash
docker compose -f docker-compose.yml up -d --build
```

Services and volumes:

| Piece | Detail |
|---|---|
| `app` | FastAPI :8000 + Streamlit :8501; healthcheck hits `/health` |
| `redis` | Redis 7 (rate limiting / caching via `REDIS_URL`), AOF on |
| `nginx` | Reverse proxy on **:8080** |
| `lotto-data` | Named volume at `/app/data` — the SQLite database |
| `lotto-redis` | Named volume for Redis persistence |

nginx routes (`docker/nginx.conf`): `/` → Streamlit (WebSocket-aware),
`/api/` → FastAPI (prefix stripped), `/health` → API health probe,
`/mobile/` → static build from `mobile-frontend/dist` (run `npm run build`
in `mobile-frontend/` first; an empty directory is fine).

Useful commands: `make docker-up`, `make docker-down`, `make docker-logs`.

## 3. Observability stack

With the API running on :8000, start Prometheus + Grafana:

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

- Prometheus: http://localhost:9090 — scrapes the API's `/metrics`, evaluates
  `monitoring/alerts.yml`
- Grafana: http://localhost:3000 — `admin` / `admin` by default; override with
  `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`

Alert thresholds (`monitoring/alerts.yml`): 5xx rate >1% for 5 min, prediction
p95 latency >5 s for 10 min, database down for 2 min, draw data stale >72 h,
disk usage >90%. Rules can also be evaluated app-side with
`python -m monitoring.alerting`. Alert channels: email via `notifier.py`
(`SMTP_*` + `ALERT_EMAIL_TO`) or a Discord/Slack incoming webhook via
`ALERT_WEBHOOK_URL`.

## 4. AWS

**ECS/Fargate + ALB (recommended):**

1. Build and push: `docker build -t lotto-app .` then push to ECR.
2. Task definition: run the image as-is (supervisord starts both services);
   expose container port 8000. Mount an EFS volume at `/app/data` for the
   SQLite database (equivalent to the `lotto-data` volume).
3. ALB target group: health check path `/health`, port 8000. Route dashboard
   traffic to port 8501 with a second target group if you expose it.
4. Secrets in Secrets Manager, injected as env vars: `SECRET_KEY`,
   `JWT_SECRET_KEY`, `SMTP_USERNAME` / `SMTP_PASSWORD`, `ALERT_WEBHOOK_URL`.
5. Off-site backups: set `BACKUP_S3_BUCKET=your-bucket` (task IAM role needs
   `s3:PutObject` on `lotto-backups/*`) and run
   `python database_backup.py daemon` as a sidecar or scheduled ECS task —
   it honors `BACKUP_SCHEDULE` (default `02:00`).

**EC2 alternative:** install Docker, clone the repo, and use the compose
commands from section 2 exactly as on any single host.

**RDS PostgreSQL option:** provision an RDS instance and set
`DATABASE_URL=postgresql://user:pass@host/lotto`, then run
`python migrate.py upgrade`. Nothing else changes — the URL resolution is
`settings.database_url` → `DATABASE_URL` → `sqlite:///lotto.db`.

## 5. Azure

**Container Apps:**

1. Push the image to Azure Container Registry.
2. Create a Container App from the image; set ingress on port 8000 (add a
   second app or container for the dashboard on 8501 if needed). Attach Azure
   Files mounted at `/app/data` for the SQLite database.
3. Secrets in Key Vault, referenced as Container Apps secrets: `SECRET_KEY`,
   `JWT_SECRET_KEY`, `SMTP_USERNAME` / `SMTP_PASSWORD`, `ALERT_WEBHOOK_URL`.
4. Health probes: point the liveness/readiness probe at `/health`.

**Blob backups:** set `BACKUP_AZURE_CONTAINER=your-container` plus
`AZURE_STORAGE_CONNECTION_STRING` (from the storage account) and run
`python database_backup.py backup --now` on a schedule (Azure Functions timer,
Container Apps job, or the `daemon` subcommand).

## 6. Render

1. New **Web Service** → deploy from the repo's `Dockerfile` (Render detects it
   automatically).
2. Add a **persistent disk** mounted at `/app/data` — the entrypoint symlinks
   `lotto.db` there, so the database survives deploys.
3. Environment variables: `SECRET_KEY`, `DEBUG=false`, `CORS_ORIGINS` (your
   exact frontend origins), `ADMIN_USERNAME` / `ADMIN_PASSWORD`, plus
   `SMTP_*` or `ALERT_WEBHOOK_URL` for alerts.
4. Health check path: `/health`.

The container listens on 8000/8501; Render routes external traffic to the
detected port — point it at 8000 for the API.

## 7. Production checklist

- [ ] `SECRET_KEY` (and `JWT_SECRET_KEY`) set to strong random values —
      `config_manager.validate_startup()` exits with code 1 if `DEBUG=false`
      and the key is still a placeholder
- [ ] `DEBUG=false`
- [ ] `CORS_ORIGINS` lists explicit origins — a wildcard entry with
      `DEBUG=false` is also fatal at startup
- [ ] `ADMIN_USERNAME` / `ADMIN_PASSWORD` changed from defaults; admin seeded
      with `make seed-admin` (`JWT_ADMIN_PASSWORD` env var, optional
      `JWT_ADMIN_USERNAME`)
- [ ] Alert channel configured: SMTP (`SMTP_HOST`/`SMTP_SERVER`,
      `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`) or
      `ALERT_WEBHOOK_URL`
- [ ] Scheduled backups: cron `0 2 * * * cd /app && python database_backup.py backup`
      or Windows Task Scheduler running the same command (or run the `daemon`
      subcommand, honoring `BACKUP_SCHEDULE`)
- [ ] Migrations applied: `python migrate.py upgrade`
      (verify with `python migrate.py check`)
- [ ] Backups verified: `python database_backup.py verify <file>` and a test
      restore before go-live

## 8. Upgrades & rollbacks

```bash
# Upgrade
git pull
pip install -r requirements.txt
python migrate.py upgrade            # or: make migrate
python migrate.py check              # confirm DB is at head

# Rollback one migration (or to a revision)
python migrate.py downgrade          # default: -1
python migrate.py downgrade 001
```

Restoring data from a backup (integrity-checked, WAL-safe snapshots):

```bash
python database_backup.py list --days 30
python database_backup.py restore backups/lotto_20260806_140046.db
python database_backup.py restore <file> --target lotto.db   # custom target
```

Backups are gzip-compressed after 7 days and pruned after
`BACKUP_RETENTION_DAYS` (default 30). After a restore, run
`python migrate.py check` to confirm the schema version matches the deployed
code before restarting services.
