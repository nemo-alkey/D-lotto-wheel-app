# Changelog

All notable changes to the NZ Lotto Wheel Analysis Platform.

## [2.0.0] — 2026-06

### Added
- **Lotto Strike** — exact-order matching for first 4 balls (Div 1–4)
- **Multi-draw backtest** with jackpot rollover — $50M Div1 cap, forced must-win at draw 10
- **PostgreSQL support** via SQLAlchemy Core — set `DATABASE_URL` to switch databases
- **Pydantic settings** (`settings.py`) — all configuration centralised, overridable via `.env`
- **XGBoost + SHAP** — ML predictor with interactive force plots in Streamlit
- **ProgressCallback** class — `st.progress()` support for long-running operations
- **Notification Settings** dashboard — toggle email/desktop alerts, min division threshold, wheel monitoring
- **Performance Monitor** dashboard — cache stats, memory/CPU (psutil), session state inspector
- **Smart caching** — ML model cached by draw hash, backtest results keyed by wheel+draws
- **Cache TTL** configurable via `CACHE_TTL_SECONDS` in settings
- **Selenium check** CLI — `python update_draws.py --check-selenium`

### Changed
- Database layer rewritten from raw `sqlite3` to SQLAlchemy Core (backward-compatible API)
- `prize_calculator.py` completely reworked — `allocate_pool()`, `apply_jackpot()`, Strike functions
- `backtest.py` — added `run_multi_draw_backtest()`, `simulate_strike_ev()`, `ProgressCallback`
- `notifier.py` — added `notify_draw_results()`, `notifier_settings` table with CRUD helpers
- `scheduler.py` — integrated with `notify_draw_results()` and `pipeline_stats` logging
- Dashboard now has 25+ pages (was 20+)
- API now has 40+ endpoints (was 30+)
- README rewritten with Docker, PostgreSQL, Strike, and API docs links

### Fixed
- Selenium error messages now include step-by-step setup guides
- Streamlit/uvicorn added to `requirements.txt`
- Git push timeout documented in README Troubleshooting

---

## [1.0.0] — 2026-05

### Added
- **Bluskov wheels** — single1, single2, double, five-if-six, jackpot7
- **Albert's Lotto Code** — positive/negative, block analysis, sum range, numerical attraction
- **Bayesian predictors** — Dirichlet-Multinomial, Thompson sampling, hierarchical bonus
- **Ensemble predictor** — walk-forward weight calibration fusing 4 methods
- **Genetic Algorithm** wheel parameter optimisation
- **Backtesting** — historical backtest, bonus impact, bootstrap CI, paired t-tests
- **Streamlit dashboard** — 20+ pages covering analysis, prediction, backtesting
- **FastAPI REST API** — 30+ endpoints for programmatic access
- **Background scheduler** — APScheduler runs Thu/Sun, fetches draws, checks tickets
- **Notifications** — email (SMTP), desktop toast (plyer), file-based alert logging
- **Ticket wizard** — 8-step guided ticket generation
- **CSV import/export** — draw data and ticket management
- **Wheel generation** — abbreviated wheels with include/exclude and bonus coverage
- **Compliance scoring** — Lotto Code compliance across 4 dimensions
- **Docker support** — Dockerfile + docker-compose.yml with persistent volumes
- **Alembic migrations** — SQLAlchemy-based schema management
- **JWT authentication** — user registration, login, admin roles

### Technical Foundation
- SQLite database with unified `lotto.db` schema
- MyLotto API integration with retry + exponential backoff
- HTML and Selenium fallback scrapers
- Prize calculator with API-driven live payouts and static fallbacks
- Environment variable configuration via `.env`
- Comprehensive test suite (`test_lotto.py`)
