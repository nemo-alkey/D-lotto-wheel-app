# Architecture

A map of the modules and how data flows through them.

---

## Layer diagram

    External sources          Local storage           Analysis / ML
    ----------------          -------------           ------------

    Official Lotto NZ   ->    data/lotto.db     ->    steps/* (markov,
      (via draw-number          (draws table,          frequency, entropy,
       API endpoint)             user tables,           bayesian_fusion,
                                 monitoring)            deep_learning,
                                                        clustering,
                                                        monte_carlo)
            |                       |                       |
            v                       v                       v
      html_scraper.py         update_draws.py         predictions.py
      crawler.py              backfill_draws.py       predict_ml.py
      selenium_scraper.py     repair_powerball_       ensemble.py
                              zero.py
            |                       |
            v                       v
      powerball_rules.py      database.py             prize_calculator.py
      (era validation)        (SQLAlchemy)            (division logic)
            |                       |                       |
            +----------+------------+-----------------------+
                       |
                       v
                User-facing surfaces
                --------------------
                api.py          (FastAPI REST)
                dashboard.py    (Streamlit UI)
                main.py         (CLI)
                pipeline.py     (orchestrator)

---

## Module responsibilities

### Ingestion layer

| Module | Responsibility |
|---|---|
| powerball_rules.py | Single source of truth for era rules and pool sizes |
| update_draws.py | Fetch latest draws, validate, insert into DB |
| backfill_draws.py | Fill gaps by draw number; idempotent |
| repair_powerball_zero.py | Fix corrupted Powerball=0 rows from legacy clamps |
| html_scraper.py, crawler.py, selenium_scraper.py | Alternate scrapers for different site rendering |
| migrate_rule_era.py | Add rule_era column and backfill it |

### Storage layer

| Module | Responsibility |
|---|---|
| database.py | SQLAlchemy models and query helpers |
| data/lotto.db | SQLite database with draws table (indexed on draw_date and draw_number) |

The draws table has columns: draw_id, draw_number, draw_date, numbers, bonus, powerball, rule_era.

### Analysis layer

| Module | Responsibility |
|---|---|
| steps/historical.py | Load draws with era-aware filtering |
| steps/frequency.py | Number frequency, hot/cold, overdue |
| steps/markov.py | Markov transition model on draw sequences |
| steps/entropy.py | Entropy and information-theoretic measures |
| steps/decay.py | Recency-weighted frequency |
| steps/bayesian_fusion.py | Bayesian combination of feature signals |
| steps/bayesian_fusion_with_mechanics.py | Extended fusion with ball-mechanics priors |
| steps/clustering.py | Number clustering |
| steps/monte_carlo.py | Monte Carlo simulation |
| steps/deep_learning.py | Neural network predictions |
| steps/generate_ticket.py | Assemble final tickets |

### Modelling layer

| Module | Responsibility |
|---|---|
| era_features.py | Era guard; blocks mixed-era PB training |
| predictions.py | Non-ML prediction (frequency, gap, z-score) |
| predict_ml.py | ML-backed prediction |
| ensemble.py | Combine predictions across models |
| train_ml_model.py | Model training with time-based split |

### Prize layer

| Module | Responsibility |
|---|---|
| prize_calculator.py | NZ Lotto + Powerball division logic, pool allocation |
| powerball_rules.py | pb_fixed_prizes(date) for era-aware Div 7 / Div 8 amounts |

### Wheel layer

| Module | Responsibility |
|---|---|
| lotto_wheels.py | Wheel definitions and load/analyse helpers |
| wheel_generator.py | Abbreviated wheel generator (greedy set cover) |
| abbreviated_wheel.py | Wheel primitives and small helpers |

### User-facing layer

| Module | Responsibility |
|---|---|
| api.py | FastAPI application; all REST endpoints |
| dashboard.py | Streamlit UI (multi-tab) |
| main.py | CLI entry point |
| pipeline.py | Orchestrates the analysis-to-ticket pipeline |

### Support

| Module | Responsibility |
|---|---|
| config/settings.py | Pydantic settings, startup validation |
| monitoring/ | Prometheus middleware, health checks |
| backtest.py | Historical backtesting |
| scripts/ | Operational scripts (backfill, repair, deploy checks) |

---

## Data flow

### Ingestion

    Official API
        |
        v
    fetch_draw_by_number(draw_num)  ->  dict
        |
        v
    validate_powerball(pb, draw_date)  ->  raises on out-of-range
        |
        v
    insert_draw(conn, draw)  ->  INSERT ... rule_era=...
        |
        v
    data/lotto.db

Every write validates the era. No silent clamps.

### Analysis

    data/lotto.db
        |
        v
    filter_draws_by_era(draws, 'post_2026_09_16')  ->  [draw, ...]
        |
        v
    check_single_era(...)  ->  raises if mixed without opt-in
        |
        v
    steps/*.py  ->  feature vectors, scores, candidate sets

### Prediction

    features
        |
        v
    predictions.py / predict_ml.py / ensemble.py
        |
        v
    candidate number sets + confidence scores
        |
        v
    generate_ticket.py  ->  final tickets

### Prize calculation

    draw + ticket  ->  matched mains, bonus hit, PB hit
        |
        v
    resolve_divisions(main, bonus, pb, draw_date)
        |
        v
    (lotto_div, pb_div)
        |
        v
    get_prize_for_matches(...)  ->  prize dict

---

## Extension points

- New analysis step: add steps/your_step.py, register it in the pipeline.
- New scraper: implement fetch_draw_by_number(draw_num) -> dict, validate via powerball_rules.
- New prompt for the prompt pack: edit scripts/prompts/catalog.psd1, add a new entry, run the runner.
- New API endpoint: add to api.py; the security middleware and rate limiter apply automatically.

---

## Conventions

- All new modules start with `from __future__ import annotations`.
- Public functions have type annotations; mypy runs clean.
- Era-sensitive code imports from powerball_rules rather than hardcoding 10 or 14.
- Tests live in tests/unit, tests/integration, or tests/e2e depending on scope.