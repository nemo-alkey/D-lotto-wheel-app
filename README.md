# NZ Lotto Powerball — Wheel Analysis & Prediction Platform

A comprehensive Python platform for NZ Lotto Powerball (6/40 + Bonus 1–40 + PB 1–10)
wheel analysis, prediction, backtesting, and ticket generation.

**Lotto Rules 2025 compliant** — Powerball, Lotto-only, Strike, and jackpot rollover.

---

## Quick Start

### One-command start (local / Codespaces)

```bash
bash start.sh
```

This installs dependencies, initialises the database, and starts both the
Streamlit dashboard (port 8501) and FastAPI server (port 8000) in the background.

### Docker

```bash
docker compose up --build
```

The Docker image bundles the database, all dependencies, and runs both services
via supervisord.  Persistent data is stored in a Docker volume.

### Manual setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run database migrations (create/update tables)
python migrate.py

# Populate the draw database (run daily/weekly)
python update_draws.py

# Check Selenium/ChromeDriver readiness (optional)
python update_draws.py --check-selenium

# Launch the Streamlit dashboard
streamlit run dashboard.py

# Start the FastAPI server
uvicorn api:app --host 0.0.0.0 --port 8000
```

### PostgreSQL (optional)

Set `DATABASE_URL` in `.env` or environment, then run migrations:

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/lotto
python migrate.py
```

The platform uses SQLAlchemy Core and supports SQLite (default) and PostgreSQL
out of the box.  See `.env.example` for all configuration options.

---

## API Documentation

Interactive API docs are served by FastAPI:

| Endpoint | Description |
|----------|-------------|
| [http://localhost:8000/docs](http://localhost:8000/docs) | Swagger UI — try endpoints interactively |
| [http://localhost:8000/redoc](http://localhost:8000/redoc) | ReDoc — clean, readable API reference |

---

## Project Structure

### Core Modules

| File | Purpose |
|---|---|
| `dashboard.py` | Streamlit web dashboard (25+ pages) |
| `api.py` | FastAPI REST API (40+ endpoints) |
| `main.py` | CLI menu + `optimize-wheel` sub‑command |
| `lotto_wheels.py` | Bluskov wheels, draw loading, statistical analysis, `check_all_wheels()` |
| `prize_calculator.py` | NZ Lotto division rules, API prize fetching, pool allocation, jackpot rollover, Strike |
| `database.py` | SQLAlchemy database layer (SQLite + PostgreSQL) |
| `database_engine.py` | SQLAlchemy engine factory with multi-DB support |
| `settings.py` | Pydantic BaseSettings — centralised configuration via `.env` |
| `update_draws.py` | Fetch latest draws from MyLotto API with retry + fallback |
| `data_pipeline.py` | Unified data fetching pipeline (API → HTML → Selenium) |

### Prediction & Analysis

| File | Purpose |
|---|---|
| `predictions.py` | XGBoost predictor with SHAP force plots, `BonusBayesian`, `HierarchicalBonusPredictor` |
| `ensemble.py` | `EnsemblePredictor` — walk‑forward weight calibration fusing 4 sub‑predictors |
| `block_analysis.py` | Positional block analysis (6 slots × 4 buckets) |
| `albert_analysis.py` | Positive/Negative classification, Albert recommended pool |
| `sum_analysis.py` | Dynamic sum-range with volatility‑adjusted multipliers |
| `analysis_bonus_pairs.py` | Bonus‑main co‑occurrence matrix, top pairs, top triplets |
| `compliance_scorer.py` | Lotto Code compliance scoring (0–100) |
| `wheel_validator.py` | Monte Carlo Bluskov guarantee validation |
| `wheel_generator.py` | Abbreviated wheel generator with `prefer_numbers`, `include/exclude`, `max_bonus_coverage` |
| `ga_optimizer.py` | Genetic Algorithm optimising wheel parameters for max EV |

### Backtesting & Simulation

| File | Purpose |
|---|---|
| `backtest.py` | Historical backtest, multi‑draw jackpot rollover, bonus impact, `simulate_bonus_ev()`, `simulate_strike_ev()`, bootstrap CI, paired t‑tests |
| `rotation_scheduler.py` | Bayesian rotation plan with optional bonus picks |

### Automation & Notifications

| File | Purpose |
|---|---|
| `scheduler.py` | APScheduler daemon — fetch draws Thu/Sun, check tickets, alert on wins |
| `notifier.py` | Email (SMTP), desktop toast (plyer), file‑based alert logging, `notifier_settings` table |
| `ticket_wizard.py` | 8‑step Streamlit wizard for guided ticket generation |

---

## Dashboard Pages

| Page | Description |
|---|---|
| **Wheels & Tickets** | Overview cards, detailed wheel views, Lotto Code scores |
| **Statistical Report** | Positive/negative split, block analysis, sum range, Bayesian, Thompson sampling |
| **Frequency Chart** | Main numbers & Powerball frequency bar charts |
| **Check Draw** | Check any wheel against custom draw numbers |
| **Check Latest Draw** | Auto‑fetch latest draw, check all wheels, bonus‑match toggle, Lotto‑only tab |
| **Strike Check** | Enter 4 numbers in exact order, compare against latest draw's first 4 balls |
| **Custom Wheel Builder** | Generate abbreviated wheels, Albert pool, include/exclude, GA auto‑optimize |
| **Bonus Ball Analysis** | Frequency bar chart, stats table, prediction model (Basic/Hierarchical Bayesian), CSV export |
| **Predictions** | Bonus prediction (Bayesian, Gap, Ensemble), weight evolution chart |
| **EV Simulation** | Monte Carlo bonus‑premium simulation |
| **Bonus–Main Co‑occurrence** | Heatmap, per‑bonus top pairs, top triplets |
| **Rotation Scheduler** | Generate rotation plan, include bonus, save tickets |
| **Backtest Results** | Single‑wheel bonus impact, multi‑wheel comparison with bootstrap CI + t‑tests, clear cache |
| **Multi‑Draw Backtest** | Consecutive draw simulation with jackpot rollover, $50M cap, forced distribution at draw 10 |
| **Block Analysis** | Positional block heatmap, compliance validation |
| **Wheel Explorer** | Bluskov guarantee validation, pair‑coverage heatmap |
| **Live Monitor** | Scheduled check status, alert log, manual check trigger |
| **Notification Settings** | Toggle email/desktop alerts, set min division threshold, choose monitored wheels, send test alert |
| **Ticket Wizard** | 8‑step guided ticket generation |
| **International Lotteries** | Fetch Powerball, Mega Millions, EuroMillions results via APIVerve |
| **ML Predictor** | XGBoost model with SHAP bar chart, individual force plots, ZIP download |
| **Performance Monitor** | Cache stats, memory/CPU usage (psutil), session state inspector |
| **Export** | Download wheel tickets as CSV |

---

## API Endpoints

### Wheels & Analysis
| Method | Endpoint | Description |
|---|---|---|
| GET | `/wheels` | List all wheels with metadata |
| GET | `/wheel/{name}` | Get a wheel's tickets |
| POST | `/check` | Check a wheel against a draw |
| GET | `/check-strike?n1=…&n2=…&n3=…&n4=…` | Check Strike against latest draw |
| GET | `/stats` | Full statistical report |
| GET | `/api/bonus/stats` | Bonus ball statistics |
| GET | `/backtest/bonus_impact?wheel_name=X` | Bonus impact report |

### Predictions
| Method | Endpoint | Description |
|---|---|---|
| GET | `/predict/bonus_bayesian?k=5` | Basic Bayesian bonus prediction |
| GET | `/predict/bonus_gap?k=5` | Gap‑method bonus prediction |
| GET | `/predict/bonus/hierarchical?k=5&halflife=90` | Hierarchical Bayesian with error bars |
| GET | `/predict/bonus/probability?num=15` | Probability for specific bonus number |
| GET | `/predict/ensemble?main=15&bonus=5&pb=3` | Ensemble prediction |

### Simulation
| Method | Endpoint | Description |
|---|---|---|
| POST | `/ev_simulation` | Monte Carlo bonus EV simulation |

---

## CLI Commands

```bash
# Run the interactive menu
python main.py

# GA wheel optimisation
python main.py optimize-wheel --generations 30 --population 50 --seed 42

# Single-draw backtest
python backtest.py --wheel single1 --draws 500
python backtest.py --wheel double --draw-pb 3

# Multi-draw backtest with jackpot rollover
python backtest.py --wheel jackpot7 --multi --num-draws 20 --start-draw 100

# Check Selenium setup
python update_draws.py --check-selenium

# Rotation scheduler (print + CSV + DB)
python rotation_scheduler.py
python rotation_scheduler.py --include-bonus --json

# Alert daemon (background)
python scheduler.py --daemon

# One‑off alert check
python scheduler.py
```

---

## Environment Variables

See `.env.example` for the complete list.  Key variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///lotto.db` | SQLAlchemy DB URL (set to `postgresql://...` for PostgreSQL) |
| `DIV1_CAP` | `50000000` | $50M maximum per Div 1 winner |
| `SMTP_SERVER` | `smtp.gmail.com` | SMTP server for email alerts |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` | — | Email address |
| `SMTP_PASSWORD` | — | App password |
| `JWT_SECRET_KEY` | (built-in default) | Secret for JWT tokens |
| `USE_SELENIUM_FALLBACK` | `false` | Enable Selenium fallback scraper |
| `CACHE_TTL_SECONDS` | `3600` | Streamlit cache TTL |

---

## Database Schema

**`lotto.db`** — main database (SQLAlchemy Core, supports SQLite + PostgreSQL):

```sql
CREATE TABLE draws (
    draw_id    INTEGER PRIMARY KEY,
    draw_date  TEXT NOT NULL UNIQUE,
    numbers    TEXT NOT NULL,      -- comma-separated: "11,12,17,22,28,32"
    bonus      INTEGER CHECK (bonus BETWEEN 1 AND 40),
    powerball  INTEGER CHECK (powerball BETWEEN 1 AND 10)
);
```

Additional tables: `epochs`, `pipeline_stats`, `notifier_settings`, `rotation_history`.

---

## Wheel Definitions

Five Bluskov wheels are pre‑built in `lotto_wheels.py`:

| Name | Tickets | Pool | Guarantee |
|---|---|---|---|
| `single1` | 20 | 10 | 4‑win if 4 pool numbers drawn |
| `single2` | 20 | 10 | 4‑win if 4 pool numbers drawn |
| `double` | 88 | 10 | Two 4‑wins if 4 pool numbers drawn |
| `five-if-six` | 11 | 11 | 5‑win if all 6 drawn from pool |
| `jackpot7` | 7 | 7 | Jackpot (6‑win) if all 6 drawn from pool |

Custom wheels can be generated via `wheel_generator.py`.

---

## NZ Lotto Division Rules

### Powerball (must match Powerball number)

| Division | Main Matches | Bonus | Pool % |
|---|---|---|---|
| Div 1 | 6 | — | 85.74% (capped at $50M) |
| Div 2 | 5 | Required | 2.23% |
| Div 3 | 5 | — | 2.23% |
| Div 4 | 4 | Required | 0.60% |
| Div 5 | 4 | — | 4.64% |
| Div 6 | 3 | Required | 4.56% |
| Div 7 | 3 | — | Fixed ($15) |

### Lotto Strike (first 4 balls in exact order)

| Division | Name | Matches | Prize |
|---|---|---|---|
| Div 1 | Strike Four | All 4 in exact order | ~65% of pool |
| Div 2 | Strike Three | First 3 in exact order | ~20% of pool |
| Div 3 | Strike Two | First 2 in exact order | ~15% of pool |
| Div 4 | Strike One | First 1 in exact order | Fixed ($1.00) |

---

## Key Features

- **25+ dashboard pages** covering every aspect of Lotto analysis
- **40+ API endpoints** with interactive Swagger/ReDoc docs
- **Multi‑draw jackpot rollover** — $50M Div1 cap, forced must‑win at draw 10
- **Lotto Strike** — exact‑order matching for the first 4 balls
- **XGBoost + SHAP** — ML predictions with interactive force plots
- **PostgreSQL support** — SQLAlchemy Core with SQLite fallback
- **Pydantic settings** — all config in one place, overridable via `.env`
- **Bluskov wheel validation** via Monte Carlo simulation
- **Hierarchical Bayesian bonus predictor** with recency decay
- **Ensemble predictor** fusing 4 methods with walk‑forward calibration
- **Genetic Algorithm** wheel parameter optimisation
- **Bootstrap confidence intervals** and paired t‑tests
- **Background scheduler** with email + desktop alerts
- **Notification Settings** dashboard — toggle alerts, set thresholds
- **Performance Monitor** — cache stats, memory/CPU, session inspector
- **Smart caching** — ML model cached by draw hash, backtest results keyed by parameters
- **Docker Compose** support with persistent volumes

---

## Testing

```bash
pytest test_lotto.py -v
```

---

## Troubleshooting

### Git Push Timeout in Codespaces

Use a GitHub Personal Access Token or configure SSH keys:

```bash
# Option 1: PAT
git config --global credential.helper store
# Next push will prompt for username + token (paste token as password)

# Option 2: SSH
ssh-keygen -t ed25519 -C "your-email@example.com"
# Add the public key to https://github.com/settings/keys
git remote set-url origin git@github.com:nemo-alkey/D-lotto-wheel-app.git
```

### Selenium / ChromeDriver

```bash
python update_draws.py --check-selenium
```

### PostgreSQL Connection

```bash
# Start a Postgres container
docker run -d --name lotto-pg -e POSTGRES_USER=lotto -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=lotto -p 5432:5432 postgres:16

# Set env var and migrate
export DATABASE_URL=postgresql://lotto:secret@localhost:5432/lotto
python migrate.py
```

---

## Links

- [API Docs (Swagger)](http://localhost:8000/docs)
- [API Docs (ReDoc)](http://localhost:8000/redoc)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CHANGELOG.md](CHANGELOG.md)
- [.env.example](.env.example)
