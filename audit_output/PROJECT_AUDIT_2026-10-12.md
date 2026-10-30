# Project Check & Audit — Lotto Wheel App
**Date:** 2026-10-12
**Scope:** codebase health, test status, data integrity, and readiness for the new NZ Powerball rules (effective 13 Sep 2026, first new-rules draw 16 Sep 2026).

---

## 1. Executive Summary

The project is functionally healthy at its core (210/215 tests pass), but it is **not ready for the new Powerball rules**. Every Powerball range assumption in the codebase is hardcoded to **1–10**, and the prize logic knows only **7 divisions**. Under the new rules (Powerball 1–14, 8 divisions, new fixed $12 Division 8, Div 1 odds 1 in 53.7M, jackpot $5M–$60M), the draw-ingestion pipeline will reject or silently corrupt new draws, and all prize/prediction math downstream is wrong. On top of that, the database already has a pre-existing Powerball data-corruption problem (104 draws with Powerball stored as 0), and the draw pipeline has not run since 2026-08-31, so the entire September 2026 changeover window is missing from the data.

**Bottom line: draw ingestion is currently broken-by-design for any draw from 16 Sep 2026 onward.**

---

## 2. The New Rules (baseline for the audit)

Source: Lotto NZ announcement (see `docs/powerball_2026_changes.txt`, copied from the provided attachment) plus public corroboration:

| Item | Old rules | New rules (from 13/16 Sep 2026) |
|---|---|---|
| Powerball pool | 1–10 | **1–14** (four new balls 11–14) |
| Powerball divisions | 7 | **8** — new Division 8, fixed **$12** prize |
| Div 1 odds per line | 1 in 38,383,800 (= C(40,6)×10) | **1 in 53,737,320** (= C(40,6)×14) |
| Starting jackpot | $4M | **$5M** |
| Maximum jackpot | $50M | **$60M** ("Must Be Won" at cap) |
| Ticket price | unchanged | unchanged |

Division 8 winning condition per third-party references: **2 main numbers + Powerball**, fixed $12, ~1 in 657. Note: sources conflict on whether the bonus ball is also required (powerball.net says 2 main + Powerball; Stuff reported "two Lotto numbers, the bonus ball and the Powerball"). **Verify the exact rule against the official Lotto NZ rules PDF before coding it.**

---

## 3. CRITICAL Findings — breaks under the new rules

### 3.1 Draw ingestion rejects Powerball 11–14
`update_draws.py:131` — `if not (1 <= powerball <= 10): raise ValueError(...)` → any new-rules draw aborts the API path and falls back to the HTML scraper. This validation must become date-aware (pre/post 2026-09-16) or simply allow 1–14 going forward.

### 3.2 Scrapers silently corrupt out-of-range Powerballs to 0
Same clamp pattern in three fetchers:
- `html_scraper.py:120` — `"powerball": powerball if 1 <= powerball <= 10 else 0`
- `crawler.py:176` — identical
- `selenium_scraper.py:226` — identical

A new-rules draw of e.g. Powerball 12 will be **stored as 0** with no error. This is the worst kind of failure: silent, and it poisons every downstream statistic, backtest and ML feature that touches the Powerball column.

### 3.3 Prize logic has no Division 8
`prize_calculator.py:80 resolve_divisions()` returns `(None, None)` for `main_matches < 3` — the new Div 8 (2 main + PB, $12) can never resolve. Consequences: prize estimation under-reports winnings; every `main_matches == 2` ticket with the Powerball is scored as a loss. Related: `settings.py:181-192` holds Powerball prize-pool percentage shares "for Divisions 1–7" with fixed-prize deduction documented as Div 7 only — the new fixed $12 Div 8 (and the new Div 7 structure) changes the pool math.

### 3.4 Powerball range 1–10 hardcoded in 20+ places
Central constant files:
- `main.py:50`, `pipeline.py:16` — `NUM_POWERBALL = 10`
- `steps/markov.py:25`, `steps/frequency.py:21`, `steps/entropy.py:21`, `steps/deep_learning.py:56`, `steps/bayesian_fusion.py:29`, `steps/bayesian_fusion_with_mechanics.py:29`, `steps/decay.py:23`, `steps/clustering.py:14`, `steps/monte_carlo.py:22` — all `NUM_POWERBALL = 10` (ML/normalization/output-layer sizes)
- `abbreviated_wheel.py:20` — `PB_MIN, PB_MAX = 1, 10`

Input/validation surfaces:
- `api.py:614` — request model `powerball: int = Field(ge=1, le=10)` (API rejects PB 11–14)
- `lotto_wheels.py:458` — validation `powerball > 10` → error
- `key_number_wheel.py:44` — CLI validation
- `dashboard.py:3066` (number input max 10), `dashboard.py:4068` (`"Powerball": range(1, 11)`), `ticket_wizard.py:151` (selectbox 1–10), `abbreviated_wheel.py:209` (max 10)
- `backtest.py:1298` — CLI `--powerball-override` help "1-10"

All ML models trained with a 10-way Powerball output head (`steps/deep_learning.py:56` output sizing) are structurally stale under 14 values; predictions for PB 11–14 can never be emitted.

### 3.5 Draw database is 6+ weeks stale and missing the changeover
- DB `data/lotto.db` ends at **2026-08-29**; `update_draws.log` last run **2026-08-31**. Every draw from 2026-09-02 onward is missing — including the entire 13–16 Sep rule change and all new-rules draws to date.
- When the scheduler next runs against a post-16-Sep draw it will hit finding 3.1/3.2 (reject → scraper fallback → store PB as 0).

---

## 4. HIGH Findings — data integrity already damaged

### 4.1 104 Powerball-era draws stored with Powerball = 0
Query against `data/lotto.db`:
- 814 total draws with `powerball = 0`; 704 are pre-2001 (legitimate — Powerball did not exist).
- **104 are post-2001 Powerball-era draws with PB = 0** (6 in 2001, 36 in 2025, 68 in 2026) — e.g. 2026-08-26 (should have a PB 1–10 under old rules). These match exactly the scraper clamp pattern in 3.2: a fetch/parse failure stored 0 instead of raising.
- Zero draws currently have PB > 10.

Recommended: backfill PB for those 104 draws from the MyLotto archive (the `backfill_*.py` scripts suggest this was done for main numbers; Powerball needs the same treatment), and change the scrapers to fail loudly (return None / raise) instead of writing 0.

---

## 5. MEDIUM Findings — configuration & features

- **`config/jackpot_thresholds.json` has no NZ Powerball game at all** — arbitrage/EV analysis covers Powerball US, Mega Millions, EuroMillions and NZ Lotto only. The new $5M start / $60M cap / Must-Be-Won rule would need a new game entry if NZ Powerball EV scanning is wanted.
- **`prize_cache.json`** (fallback prize payload, dated 2026-08-26) reflects the old 7-division structure.
- **Documentation drift:** `predictions.py:3`, `lotto_wheels.py:3`, `backtest.py:601`, `steps/historical.py:51`, `steps/decay.py`, `steps/monte_carlo.py` all describe "PB 1-10" as the game definition.
- **Jackpot constants:** no references found to the old $4M start / $50M cap in code (good — nothing hardcodes the old jackpots), but equally nothing implements the new $5M / $60M / Must-Be-Won cap for NZ Powerball.

---

## 6. Test & CI Health

Run: `venv/Scripts/python.exe -m pytest tests/ -q` → **210 passed, 5 failed**, plus **1 collection error** (the failed file never runs at all).

| Failure | Cause |
|---|---|
| `tests/unit/test_wheel_generator.py` (collection error) | Imports `generate_abbreviated_wheel` which no longer exists in `wheel_generator.py` — test not updated after refactor |
| `tests/e2e/test_dashboard_smoke.py` ×2 | Same root cause: dashboard imports the missing symbol |
| `tests/integration/test_database.py::TestInsertDraw` ×2 | `sqlite3.OperationalError: no such column: draw_number` — test fixture schema not updated after the `draw_number` column migration |
| `tests/integration/test_monitoring.py::test_wheels_counter_increments` | Same missing-symbol import |

All six trace back to two refactor artifacts (missing wheel-generator function; stale test DB schema), not to Powerball logic. CI currently cannot be green.

---

## 7. Security & Repo Hygiene

**Good:** `.env`, `deepseek api key.txt`, `bmail code.txt`, `*.bak`, `*.log`, `prize_cache.json` and the DB are all in `.gitignore`; `git ls-files` confirms no secrets are tracked.

**Concerns:**
- Plaintext secret files (`deepseek api key.txt`, `.env`, `config/secrets.py` nearby) live in the working tree; anyone/anything copying the folder leaks them.
- Root directory is cluttered with one-off scripts (`Untitled-1.py`, `check_fetch.py`, `top_10.py`, `debug_backfill.py`, 6× `backfill_*.py`, `diagnose_*.py`) and duplicates (`winning_numbers.xlsx.xlsx`, `api.py.bak`, `main.py.bak`, `import_excel.py` vs `import_excel_fixed.py`).
- 26 modified tracked files are uncommitted; CI history shows recent churn ("Restore accidentally deleted pyproject.toml…").

---

## 8. Prioritized Action List

1. **Ingestion first:** make `update_draws.py` validation accept PB 1–14 (ideally date-aware), and change all three scrapers to raise/fail on an out-of-range Powerball instead of writing 0. Then run the backfill to recover draws 2026-09-02 → present.
2. **Repair history:** backfill Powerball for the 104 post-2001 draws stored as 0.
3. **Prize engine:** add Division 8 to `resolve_divisions()` after confirming the official rule (2 main + PB, or 2 main + bonus + PB), update `settings.py` pool-percentage config and fixed-prize deduction, and refresh `prize_cache.json`.
4. **Constants:** introduce a single `POWERBALL_MAX = 14` (game-config driven, ideally with an effective-from date) and replace all 20+ hardcoded 10s, including ML output-head sizes; retrain Powerball models.
5. **UI/API surfaces:** update the six input widgets/validators listed in 3.4.
6. **Tests:** restore `generate_abbreviated_wheel` (or update tests), refresh the test DB fixture schema with `draw_number`, then re-run the suite to green.
7. **Optional:** add NZ Powerball (new odds/prizes, $60M Must-Be-Won cap) to `config/jackpot_thresholds.json` for EV/arbitrage scanning; purge plaintext key files from the working tree or encrypt them.
