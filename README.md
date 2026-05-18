# NZ Lotto Powerball Analysis Pipeline

A multi-stage analysis pipeline for NZ Lotto Powerball (6/40 + PB 1/10) that
combines classical statistics, Bayesian inference, frequency analysis, wheel
construction, and simulated quantum methods to analyse historical draws,
generate predictions, build abbreviated lotto wheels, and produce playable
tickets.

## Pipeline Overview (12 Steps)

The analysis pipeline (`pipeline.py` + `steps/`) chains 12 stages, each
receiving and returning a shared state dict:

| Step | File | Purpose |
|------|------|---------|
| 1 | `steps/historical.py` | Load and clean draw data from SQLite |
| 2 | `steps/frequency.py` | Global occurrence probabilities (main + PB) |
| 3 | `steps/decay.py` | Recency-weighted probabilities (draw-based decay, half-life configurable via `config.py`) |
| 4 | `steps/bayesian_fusion_with_mechanics.py` | Dirichlet posterior + chi-square uniformity test + log-space fusion of frequency, decay, and mechanics priors |
| 5 | `steps/clustering.py` | K-Means clustering on probability features (dynamic k) |
| 6 | `steps/monte_carlo.py` | Efraimidis-Spirakis weighted sampling (up to 200k sims) |
| 7 | `steps/redundancy.py` | Recency + unbiased gap scores, std-normalised, cluster-weighted |
| 8 | `steps/markov.py` | First-order Markov chain on inter-draw cluster transitions |
| 9 | `steps/entropy.py` | Per-symbol Shannon entropy: -p_i x log2(p_i) |
| 10 | `config/quantum_features.py` | SPSA-trained 12-qubit variational circuit (classical simulation) |
| 11 | `config/quantum_kernels.py` | Fidelity kernel features \|psi(x_i) \| proto_j\|^2 |
| 12 | `steps/generate_ticket.py` | 12-line ticket generation with rejection sampling (max 2 overlap, max 2 PB repeats) |

## Draw Frequency

NZ Lotto Powerball holds **two draws per week** (Wednesday and Saturday).
The pipeline accounts for this through draw-based decay rather than
calendar-week-based decay:

- **`DRAWS_PER_WEEK = 2`** in [`config.py`](config.py) — when draw frequency
  changes, only this constant needs updating.
- **`DECAY_PER_DRAW = 0.98 ** (1 / DRAWS_PER_WEEK)`** — the per-draw decay
  rate is derived from the weekly half-life, so applying it across two draws
  compounds to the same 0.98 weekly decay in real time.
- Recency, gap, and Markov features in `steps/redundancy.py` and
  `steps/markov.py` operate on draw indices (not calendar dates), making
  them naturally frequency-agnostic.
- The rotation scheduler (`rotation_scheduler.py`) labels its output in
  *periods* where 1 period = 2 draws, clarifying coverage per row.

## Installation (Linux)

### Prerequisites

- Python 3.12+ (3.12 recommended; 3.10 may work but is not officially tested)
- SQLite 3
- pip

### 1. Clone and set up

```bash
git clone <repo-url> lotto-wheel-app
cd lotto-wheel-app
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install numpy scipy scikit-learn pytest
```

Optional extras:
```bash
pip install fastapi uvicorn streamlit pandas  # API / dashboard / reporting
```

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| numpy | >=1.24 | Numerical computing, array ops, random sampling |
| scipy | >=1.10 | Chi-square distribution, statistical tests |
| scikit-learn | >=1.3 | K-Means clustering, MinMaxScaler |
| pytest | >=7.0 | Test suite |
| fastapi | (optional) | REST API |
| uvicorn | (optional) | ASGI server |
| streamlit | (optional) | Interactive dashboard |
| pandas | (optional) | DataFrames for reporting / export |

## Quick Start

### Initialise the database

```bash
python3 db_schema.py
```

### Load historical data

```bash
python3 data_loader.py data.csv
```

### Run the full analysis pipeline

```python
from database import fetch_all_draws
from pipeline import run_pipeline
from steps.historical import run as s1
from steps.frequency import run as s2
from steps.decay import run as s3
from steps.bayesian_fusion_with_mechanics import run as s4
from steps.clustering import run as s5
from steps.monte_carlo import run as s6
from steps.redundancy import run as s7
from steps.markov import run as s8
from steps.entropy import run as s9
from steps.generate_ticket import run as s12

steps = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s12]
state = {"past_results": fetch_all_draws()}
state = run_pipeline(steps, state)
print("Ticket:", state["ticket_lines"])
```

### Run the CLI (main.py)

```bash
python3 main.py list-wheels
python3 main.py hot-numbers
python3 main.py simulate jackpot7 100000
python3 main.py check double "11,12,17,22,28,32 PB3"
python3 main.py recommend
python3 main.py rotate jackpot7 6
python3 main.py build-wheel mywheel "1,2,3,4,5,6,7,8"
python3 main.py update-draw 1234 "2026-01-15" "10,20,30,31,32,33" 7
```

### Run the CLI (lotto_wheels.py)

```bash
python3 lotto_wheels.py report
python3 lotto_wheels.py list-wheels
python3 lotto_wheels.py show-wheel double
python3 lotto_wheels.py export double tickets.csv
python3 lotto_wheels.py check double "11,12,17,22,28,32" 3
```

### Generate a rotation plan

```bash
python3 rotation_scheduler.py
```

Outputs a formatted table and saves `rotation_plan.csv`.

### Start the REST API

```bash
uvicorn api:app --reload
# Open http://127.0.0.1:8000/docs
```

### Run the Streamlit dashboard

```bash
streamlit run dashboard.py
```

## Lotto Wheels

The system includes 5 Bluskov preset wheels accessed via `lotto_wheels.py`:

| Wheel | Pool | Tickets | Guarantee | Cost |
|-------|------|---------|-----------|------|
| jackpot7 | 7 numbers | 7 | 6/6 (full wheel) | $10.50 |
| single1 | 10 numbers | 20 | 4/4 (100%) | $30.00 |
| single2 | 10 numbers | 20 | 4/4 (100%) | $30.00 |
| double | 10 numbers | 30 | 4/4 (97%) | $45.00 |
| five-if-six | 11 numbers | 22 | 5-if-6 | $33.00 |

Plus custom abbreviated wheels via `wheel_generator.py` (any pool 7-40 numbers).

### Division Payouts (NZ Lotto Powerball)

| Division | Condition | Est. Prize |
|----------|-----------|------------|
| Div 1 (6+PB) | 6 main + PB | $1,000,000 |
| Div 2 (5+PB) | 5 main + PB | $30,000 |
| Div 3 (5) | 5 main, no PB | $1,000 |
| Div 4 (4+PB) | 4 main + PB | $100 |
| Div 5 (4) | 4 main, no PB | $60 |
| Div 6 (3+PB) | 3 main + PB | $40 |
| Div 7 (3) | 3 main, no PB | $20 |

A ticket qualifies for exactly one division (the highest it satisfies).
PB must match for divisions marked "+PB"; PB must NOT match for the rest.

## API Endpoints

```
GET  /wheels              -- List all wheels with metadata
GET  /wheel/{name}        -- Tickets and suggested powerball for one wheel
POST /check               -- Check a wheel against a draw (JSON: wheel, draw, powerball)
GET  /stats               -- Statistical report as JSON
```

## Configuration

Key constants you may want to tune:

| Constant | File | Default | Meaning |
|----------|------|---------|---------|
| DRAWS_PER_WEEK | config.py | 2 | Number of lottery draws per week |
| DECAY_PER_DRAW | config.py | 0.98^(1/2) | Per-draw decay rate (derived from 0.98 weekly half-life) |
| ALPHA | steps/bayesian_fusion_with_mechanics.py | 1.0 | Dirichlet prior concentration |
| DEFAULT_K | steps/clustering.py | 5 | Preferred cluster count |
| CLUSTER_MODULATION | steps/monte_carlo.py | 0.3 | Cluster strength influence on MC |
| LINES | steps/generate_ticket.py | 12 | Number of ticket lines to generate |
| MAX_OVERLAP | steps/generate_ticket.py | 2 | Max shared main numbers between lines |
| N_QUBITS | config/quantum_features.py | 12 | Simulated qubit count |
| SPSA_A | config/quantum_features.py | 50.0 | SPSA gain schedule parameter |

## Testing

```bash
pytest test_lotto.py -v
pytest test_frequency.py -v
pytest test_bayesian_fusion.py -v
pytest test_clustering.py -v
pytest test_monte_carlo.py -v
pytest test_data_io.py -v
pytest test_historical.py -v
pytest test_decay.py -v
pytest test_entropy.py -v
pytest test_markov.py -v
pytest test_redundancy.py -v
pytest test_quantum.py -v
pytest test_generate_ticket.py -v
pytest test_logs.py -v
```

Test coverage includes database init/insert/dedup, frequency analysis, hot/cold
split, gap analysis, wheel verification, abbreviated wheels, CLI parsing,
division key mapping, simulation determinism, and edge cases.

## Project Structure

```
lotto-wheel-app/
  main.py                 -- CLI entry point (10+ subcommands)
  pipeline.py             -- Lightweight step chaining framework
  api.py                  -- FastAPI REST API (4 endpoints)
  dashboard.py            -- Streamlit interactive dashboard

  db_schema.py            -- SQLite schema (draws, frequencies)
  queries.py              -- Query helpers (date range, streaming)
  data_loader.py          -- CSV/JSON import into database
  data_validator.py       -- Integrity checks
  data_io.py              -- JSON save/load for generated tickets

  lotto_wheels.py         -- Wheel manager (Albert + Bluskov integration)
  wheel_generator.py      -- Full / abbreviated / key-number wheels
  wheel_dashboard.py      -- Wheel analysis dashboard
  rotation_scheduler.py   -- Rotation planner (2 draws/period)

  frequency_analysis.py   -- Frequency, hot/cold, gap, pair analysis
  distribution_analysis.py-- Odd/even, low/high distributions
  pattern_detection.py    -- Consecutive, odd/even, low/high patterns
  temporal_analysis.py    -- Sliding-window frequency trends
  copula_analysis.py       -- Gaussian copula dependence modelling
  predictions.py          -- 7 prediction methods + ensemble
  backtesting.py          -- Walk-forward historical backtesting
  report.py               -- HTML statistical report generator

  steps/                  -- 12 pipeline step modules
  config/                 -- Quantum features, kernels, logging

  test_lotto.py           -- End-to-end tests
  test_*.py               -- Individual module tests (14 files)

  run_lotto.sh            -- Convenience wrapper for lotto_wheels.py
  run_dashboard.sh        -- USB-friendly dashboard launcher
  sync_to_usb.sh          -- Sync project to FAT32 USB drive
```

## Prediction Methods

The `predictions.py` module implements 7 methods:

1. **Frequency** -- Top-6 most drawn numbers + most common PB
2. **Bayesian** -- Dirichlet-Multinomial posterior (alpha=1.0, add-one smoothing)
3. **Markov** -- Number-to-number pair transition matrix
4. **Weighted Random** -- Recency-weighted Thompson sampling (2x weight on last 20%)
5. **Due Numbers** -- Gap z-score + frequency z-score combination
6. **Pattern** -- Odd/even + low/high pattern extrapolation from last 10 draws
7. **Ensemble** -- Weighted vote across all methods

## Statistical Tests

- Chi-square uniformity test (alpha=0.05, collapses to uniform when p > 0.05)
- Unbiased gap scoring (initial + internal + final gaps)
- Coefficient of variation for dynamic cluster count selection

## USB Drive Usage (FAT32)

The project supports running from a FAT32 USB drive where Python venv symlinks
would break. Use the included scripts:

```bash
# Sync project to USB (auto-mounts /dev/sda1)
./sync_to_usb.sh

# Launch dashboard from USB
./run_dashboard.sh
```

The launcher mounts the drive with proper uid/gid, verifies Streamlit is
available (installs via --user if missing), then starts the dashboard using
the system Python interpreter (no venv).

## Bayesian Rotation (Period Planner)

The `rotation_scheduler.py` script computes Dirichlet-Multinomial posterior
probabilities for numbers 1-40 from historical draw data. Period 1 selects the
top 11 numbers by Bayesian score. Each subsequent period swaps out the weakest
number for the next-best candidate from the remaining pool. Outputs a
formatted table and `rotation_plan.csv`.

## Disclaimer

Lottery draws are independent random events. This pipeline identifies
historical patterns and statistical tendencies only. No method can predict
future draws. Output is for analytical and entertainment purposes only.
