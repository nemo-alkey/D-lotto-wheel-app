# 🐳 Docker Setup — NZ Lotto Powerball App

Package the entire Lotto analysis toolkit (Streamlit dashboard + FastAPI + all scripts) into a single Docker container for portable, reproducible deployment on any Linux machine.

## Prerequisites

- **Docker** (>= 24.0) — [install guide](https://docs.docker.com/engine/install/)
- **Docker Compose** (>= 2.24) — included with Docker Desktop; on Linux install `docker-compose-plugin`
- **Git** (to clone the repo or copy files)
- ~1.5 GB free disk space (for the image + dependencies)

## Quick Start

```bash
# 1. Clone or cd into the project directory
cd /media/racing_dev/FBC2-0CF4/lotto-wheel-app

# 2. Build the image and start the container
docker compose up -d

# 3. Check logs
docker compose logs -f

# 4. Open in your browser
#    Dashboard:  http://localhost:8501
#    API:        http://localhost:8000/docs
```

The first build will take 2–5 minutes (downloading packages). Subsequent starts are instant.

## What's Inside

| Service    | Port | URL                              |
|------------|------|----------------------------------|
| Streamlit  | 8501 | http://localhost:8501             |
| FastAPI    | 8000 | http://localhost:8000             |
| API docs   | 8000 | http://localhost:8000/docs (Swagger) |

### Services run simultaneously

- **Streamlit Dashboard** — wheel management, statistical report, frequency chart, check draw, custom wheel builder, export
- **FastAPI** — REST endpoints for `/wheels`, `/wheel/{name}`, `/check`, `/stats`

Both share the same SQLite database (`lotto_working.db`).

## Data Persistence

### How it works

The container stores all databases in a **Docker volume** mounted at `./data/`:

```
lotto-wheel-app/
├── data/               ← created automatically (persistent volume)
│   └── lotto_working.db
├── lotto_working.db    ← symlink → data/lotto_working.db
└── docker-compose.yml
```

- On **first run**: the bundled `lotto_working.db` (with ~1873 historical draws) is copied to `./data/lotto_working.db`.
- On **subsequent runs**: the existing database in `./data/` is reused — all data persists.
- `lotto.db` (used by `update_draws.py`) is created automatically with the correct schema.

### Backup / Restore

```bash
# Backup the database
cp data/lotto_working.db data/lotto_working.db.backup

# Restore from backup
cp data/lotto_working.db.backup data/lotto_working.db
docker compose restart
```

To start fresh with the bundled data:
```bash
docker compose down
rm data/lotto_working.db
docker compose up -d
```

## Updating Draws

The container does **not** auto-update draws (it would need network + cron). Two options:

### Option A: Run update manually inside the container

```bash
# Run the update script
docker compose exec lotto python3 update_draws.py

# Check the result
docker compose exec lotto python3 -c "
from lotto_wheels import load_draws
d = load_draws()
print(f'Database has {len(d)} draws (since {d[0][2]} to {d[-1][2]})')
"
```

### Option B: Add a host cron job

On the **host machine** (not inside the container), add a crontab entry:

```cron
# Runs every Wednesday and Saturday at 7:30 PM NZT
30 19 * * 3,6 cd /path/to/lotto-wheel-app && docker compose exec lotto python3 update_draws.py >> update_draws.log 2>&1
```

## Customisation

### Environment Variables

Edit `docker-compose.yml` to add:

```yaml
services:
  lotto:
    environment:
      - TZ=Pacific/Auckland        # Already set
      - SMTP_SERVER=smtp.gmail.com # For email alerts
      - SMTP_USERNAME=you@gmail.com
      - SMTP_PASSWORD=your-app-password
      - TWILIO_ACCOUNT_SID=xxx     # For SMS alerts
      - TWILIO_AUTH_TOKEN=xxx
      - TWILIO_FROM=+1234567890
```

Then restart: `docker compose restart`

### Build Arguments

| Arg           | Default          | Description                  |
|---------------|------------------|------------------------------|
| `PYTHON_BASE` | `python:3.12-slim` | Base Docker image           |

## Commands Reference

```bash
# Build / start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose stop

# Stop and remove
docker compose down

# Rebuild (after code changes)
docker compose build --no-cache
docker compose up -d

# Run a one-off command in the container
docker compose exec lotto python3 lotto_wheels.py report

# Run the test suite
docker compose exec lotto python3 -m pytest test_lotto.py -v

# Open a shell inside the container
docker compose exec lotto bash
```

## Architecture

```
┌─────────────────────────────────────────────┐
│  Docker Container                            │
│                                              │
│  ┌──────────────────┐  ┌──────────────────┐  │
│  │  Streamlit (8501) │  │  FastAPI (8000)   │  │
│  │  dashboard.py     │  │  api.py           │  │
│  └────────┬─────────┘  └────────┬─────────┘  │
│           │                     │            │
│           └─────────┬───────────┘            │
│                     │                        │
│          ┌──────────▼──────────┐             │
│          │  lotto_wheels.py     │             │
│          │  predictions.py      │             │
│          │  wheel_generator.py  │             │
│          │  backtest.py         │             │
│          │  … (all scripts)     │             │
│          └──────────┬───────────┘             │
│                     │                        │
│          ┌──────────▼──────────┐             │
│          │  lotto_working.db    │  ← volume    │
│          │  (SQLite)            │             │
│          └─────────────────────┘             │
│                                              │
│  Host volume: ./data/ → /data/               │
└─────────────────────────────────────────────┘
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Address already in use` on port 8501/8000 | Change the host port in `docker-compose.yml` (e.g., `"8502:8501"`) |
| No draws shown on the dashboard | Run `docker compose exec lotto python3 update_draws.py` |
| `lotto_working.db not found` | Run `docker compose down && docker compose up -d` to re-initialise |
| Dashboard stuck on "Loading" | Check logs: `docker compose logs dashboard` |
| Permission error on `./data/` | `sudo chown -R $(id -u):$(id -g) data/` |

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container build definition |
| `docker-compose.yml` | Service orchestration |
| `supervisord.conf` | Runs both services inside the container |
| `start.sh` | Entrypoint — initialises DB, starts services |
| `requirements.txt` | Python dependencies |
