# Contributing to NZ Lotto Wheel Analysis Platform

Welcome! This guide explains how to navigate the project and add new features.

## Project Architecture

```
lotto-wheel-app/
├── dashboard.py          # Streamlit UI (25+ pages, one elif per page)
├── api.py                # FastAPI REST API (40+ endpoints)
├── settings.py           # Pydantic BaseSettings — all config lives here
├── database.py           # SQLAlchemy Core — DB operations (SQLite + PostgreSQL)
├── database_engine.py    # Engine factory — resolves DATABASE_URL
├── prize_calculator.py   # Division rules, pool allocation, jackpot, Strike
├── lotto_wheels.py       # Wheel definitions, draw loading, statistics
├── backtest.py           # Historical & multi-draw backtesting, EV simulation
├── predictions.py        # XGBoost + SHAP prediction model
├── scheduler.py          # APScheduler — fetches draws, checks tickets, alerts
├── notifier.py           # Email/SMTP + desktop notifications + settings table
├── update_draws.py       # MyLotto API fetcher with retry + fallback
├── data_pipeline.py      # Unified fetcher (API → HTML → Selenium)
├── steps/                # Analysis pipeline steps (Bayesian, Markov, etc.)
├── config/               # Quantum ML modules
├── alembic/              # Database migrations
├── .env.example          # All environment variables documented
└── requirements.txt      # Python dependencies
```

## How to Add a New Feature

### 1. New Scraper / Data Source

1. Create a module with a function returning `{"draw_date": str, "numbers": list[int], "bonus": int, "powerball": int}`
2. Register it in `data_pipeline.py` → `DataFetcher.METHODS` list
3. Add a `_try_fetch()` branch for your method

### 2. New Prize Division

1. Add the division to `prize_calculator.py` → `resolve_divisions()` or create a new resolver
2. Update `allocate_pool()` percentages if needed
3. Add to `settings.py` → `strike_pool_percentages` or new section

### 3. New Dashboard Page

1. Add the page name to the `st.radio("Go to", [...])` list in `dashboard.py`
2. Create an `elif page == "Your Page":` block with Streamlit components
3. Use `st.cache_data(ttl=_CACHE_TTL)` for expensive computations
4. Add a "Clear Cache" button if results are cached

### 4. New API Endpoint

1. Add a route in `api.py` (e.g., `@app.get("/my-endpoint")`)
2. Use Pydantic models for request/response validation
3. Add rate limiting via `@limiter.limit(_default_limit)` or `_heavy_limit`
4. Document in the README API section

### 5. New Configuration Option

1. Add the field to `settings.py` → `Settings` class with `Field(description=...)`
2. Add a commented example to `.env.example`
3. Update `docker-compose.yml` if needed for Docker deployments

## Code Style

- **Python 3.12+** with `from __future__ import annotations`
- **Type hints** on all public functions (`list[int]`, `dict[str, Any]`)
- **Docstrings** for every public function (Google-style: Parameters, Returns)
- **Settings** always imported from `settings.py`, never hardcoded
- **Database** always accessed via `database.py` or `database_engine.py`, never raw `sqlite3`
- **Caching** via `st.cache_data(ttl=_CACHE_TTL)` loaded from settings

## Running Tests

```bash
pytest test_lotto.py -v
```

## Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
python migrate.py

# Roll back
alembic downgrade -1
```

Migrations use SQLAlchemy Core (not ORM) and support both SQLite and PostgreSQL.

## Environment Variables

Copy `.env.example` to `.env` and fill in your values.  All settings are documented
in `settings.py` with type hints and descriptions.

## Pull Request Checklist

- [ ] Code compiles (`python -m py_compile <file>.py`)
- [ ] Settings used instead of hardcoded values
- [ ] Database access via SQLAlchemy, not raw `sqlite3`
- [ ] New features documented in README
- [ ] Docstrings on all public functions
- [ ] Tests pass (`pytest test_lotto.py -v`)
