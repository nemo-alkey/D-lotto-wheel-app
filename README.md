# NZ Lotto Powerball Analysis Toolkit

Era-aware data science, wheel generation, and prediction toolkit for New Zealand Lotto (6/40) and Powerball (1/14 since September 2026).

Status: 292 tests passing, mypy clean, era-aware across the 2026 Powerball rule change.

---

## What this is

A Python application for analysing New Zealand's Lotto draws and Powerball add-on. It does four things:

1. Ingests historical draw data from official sources into a local SQLite database (data/lotto.db).
2. Analyses the data with statistical and machine-learning techniques (frequency, Markov chains, Bayesian fusion, neural nets).
3. Generates lottery wheels (covering designs) that systematically cover number combinations.
4. Predicts candidate number sets using a range of models.

It is NOT a guaranteed winning system. Lotteries are random. The value is in the data-science exercise, the tooling, and the statistical honesty about what the data does and does not show.

---

## Quick start

Requires Python 3.11-3.13 on Windows, macOS, or Linux.

    # 1. Clone / open the repo
    cd D:\lotto-wheel-app

    # 2. Create venv (one time)
    python -m venv venv

    # 3. Activate (Windows PowerShell)
    .\venv\Scripts\Activate.ps1

    # 3b. Activate (bash / zsh)
    # source venv/bin/activate

    # 4. Install dependencies
    python -m pip install -r requirements.txt

    # 5. Run the test suite
    python -m pytest tests/ -q

    # 6. Backfill any missing draws (idempotent)
    python scripts/backfill_draws.py

After that, a session typically starts with resume_tomorrow.ps1, which activates the venv, runs the suite, and checks the Powerball era wiring.

---

## Repository layout

    lotto-wheel-app/
      api.py                  FastAPI application (REST endpoints)
      dashboard.py            Streamlit dashboard (multi-tab UI)
      main.py                 CLI entry point
      pipeline.py             ML pipeline orchestration
      predictions.py          Prediction logic (frequency, gap, z-score)
      predict_ml.py           ML-backed prediction
      train_ml_model.py       Model training (era-aware)
      ensemble.py             Ensemble methods
      lotto_wheels.py         Wheel generation and analysis
      wheel_generator.py      Abbreviated wheel generator (covering designs)
      abbreviated_wheel.py    Wheel primitives
      prize_calculator.py     NZ Lotto + Powerball prize/division engine
      powerball_rules.py      Era-aware Powerball pool rules (source of truth)
      era_features.py         Era guard; blocks mixed-era PB training
      database.py             SQLAlchemy models and fetch helpers
      update_draws.py         Ingestion (scraper + DB writer)
      html_scraper.py         HTML scraper
      crawler.py              Crawler
      selenium_scraper.py     Selenium scraper (JS-heavy pages)
      backtest.py             Backtesting engine
      config/                 Settings (Pydantic)
      monitoring/             Prometheus / health-check middleware
      steps/                  Analysis steps (markov, frequency, entropy,
                              deep_learning, bayesian_fusion, clustering,
                              monte_carlo, decay, historical)
      scripts/                One-off and operational scripts
        backfill_draws.py
        repair_powerball_zero.py
        migrate_rule_era.py
        prompts/              Prompt pack runner (see docs/PROMPT_PACK.md)
      data/
        lotto.db              SQLite database (draws + user data)
      reports/                Generated reports (gitignored)
      tests/                  Pytest suite (292 tests)
        unit/
        integration/
        e2e/
      docs/                   Project documentation (this directory)
      audit_output/           Audit reports and baselines
      mypy.ini                mypy configuration

---

## Key concepts

### Era-aware Powerball rules

On 2026-09-16 the NZ Powerball pool changed from 1-10 to 1-14, with additional prize and odds changes. This is not a cosmetic change. Any code that reads, writes, or models Powerball numbers must know which era it is operating in.

Single source of truth: powerball_rules.py. Every pool size, every validation, every era-scoped decision goes through it. See docs/POWERBALL_2026.md for the full model.

### Draw ingestion

Draws are keyed by draw number, not date. The official API endpoint used by backfill_draws.py and update_draws.py accepts a draw number and returns the corresponding result. Date-based lookups are unreliable and have historically caused duplicate-draw bugs.

Ingestion validates every Powerball value against the era rules. Any out-of-range value raises immediately rather than being silently clamped.

### Wheels

An abbreviated wheel covers a chosen set of numbers with the minimum number of tickets to guarantee a specific prize condition (e.g. "if 4 of your numbers are drawn, you will have at least one ticket with 3 matches"). The generator uses greedy set covering in wheel_generator.py.

### Prize calculation

prize_calculator.py implements the official NZ Lotto and Powerball division structure, including the new Division 8 (2 main + bonus + Powerball = $12 fixed) introduced with the September 2026 change.

Key functions:

- resolve_divisions(main, bonus, pb, draw_date) returns (lotto_div, pb_div) for a set of matches.
- get_prize_for_matches(...) returns a full prize dict.
- allocate_pool(turnover, winners, ...) models pool distribution including Div 1 cap and fixed-prize deductions.

### Era guard for ML

era_features.check_single_era() refuses to train the Powerball model on mixed-era data unless the caller explicitly opts in with era_aware=True and supplies the era as a feature. With only a few post-change draws available, the guard correctly refuses to train rather than silently producing a broken model.

---

## Testing

    # Full suite
    python -m pytest tests/ -q

    # Fast subset (skip slow dashboard e2e)
    python -m pytest tests/ -q -m "not slow"

    # Type check
    python -m mypy .

    # Coverage (if pytest-cov is installed)
    python -m pytest tests/ --cov=. --cov-report=term-missing

Expected: 292 passed, mypy Success, 133 files checked.

See docs/TESTING.md for the test categories and how to add new tests.

---

## Operations

### Daily / weekly tasks

    # Backfill any new draws (safe to run any time - idempotent)
    python scripts/backfill_draws.py

    # Repair any Powerball=0 rows (safe, only touches post-2001 rows)
    python scripts/repair_powerball_zero.py

    # Run migrations (adds columns; idempotent)
    python scripts/migrate_rule_era.py

### Backups

lotto.db is the only file with real data. Back it up before any bulk operation:

    Copy-Item data\lotto.db "backups\lotto.db.$(Get-Date -Format yyyyMMdd)"

.gitignore excludes the .db-shm and .db-wal sidecar files (SQLite WAL mode); the main .db is the durable artifact.

### Deploy

Deployment scripts live in scripts/. See scripts/deploy_check.py and scripts/verify_deploy.py for the pre-deploy and post-deploy gates.

---

## Documentation index

- docs/ARCHITECTURE.md - module map and data flow
- docs/POWERBALL_2026.md - the rule change and era model
- docs/TESTING.md - test categories and conventions
- docs/PROMPT_PACK.md - prompt pack runner
- audit_output/ - audit reports and baselines

---

## Development workflow

1. Activate venv.
2. Make a change.
3. Run python -m pytest tests/ -q (fast) or the full suite.
4. Run python -m mypy . (must be clean).
5. Commit with a specific message.

Pre-commit hooks are configured in .pre-commit-config.yaml.

---

## Honest framing

These tools explore patterns in a random process. They do not and cannot predict lottery outcomes. The statistical tests in the suite are there partly to confirm this: chi-square on the full draw history does not reject uniformity, and the ML models do not reliably beat random baselines on out-of-sample data.

Use the toolkit to ask and answer questions about randomness, prizing, and expected value. Do not use it as a betting strategy.