# NZ Lotto Powerball — Research & Improvement Ideas

## Official Division Structure

### Base Game Numbers

| Component | Pool | Drawn |
|-----------|------|-------|
| Main numbers | 1–40 | 6 balls |
| Bonus ball (7th ball) | 1–40 | 1 ball (drawn from same pool after main 6) |
| Powerball | 1–10 | 1 ball (drawn separately) |

### Powerball Divisions (must match the Powerball number)

| Division | Main Matches | Bonus | PB | Source |
|----------|-------------|-------|----|--------|
| **Div 1** 🏆 | 6 | — | Yes | ~85.74% of pool after Div 7 |
| **Div 2** | 5 | Required | Yes | ~2.23% of pool |
| **Div 3** | 5 | — | Yes | ~2.23% of pool |
| **Div 4** | 4 | Required | Yes | ~0.6% of pool |
| **Div 5** | 4 | — | Yes | ~4.64% of pool |
| **Div 6** | 3 | Required | Yes | ~4.56% of pool |
| **Div 7** | 3 | — | Yes | Fixed (~$15 + bonus ticket) |

**Key rule:** All Powerball divisions require the Powerball to match. The bonus ball **upgrades** your division when matched alongside 5, 4, or 3 main numbers. Without the bonus ball, 5+PB = Div 3, 4+PB = Div 5, 3+PB = Div 7. Without PB, there is no Powerball win at all (though the Lotto-only component may still pay).

### Standard Lotto Divisions (Powerball not matched, or Lotto-only play)

| Division | Main Matches | Bonus | Approx. Pool % |
|----------|-------------|-------|----------------|
| Div 1 | 6 | — | ~34.6% |
| Div 2 | 5 | Required | ~10.1% |
| Div 3 | 5 | — | ~10.5% |
| Div 4 | 4 | Required | ~2.5% |
| Div 5 | 4 | — | ~21.5% |
| Div 6 | 3 | Required | ~20.8% |
| Div 7 | 3 | — | Bonus ticket |

### Live Prize Validation (2026-05-23 draw via MyLotto API)

| Condition | Lotto Div | Lotto Prize | PB Div | PB Prize | Total |
|-----------|-----------|-------------|--------|----------|-------|
| 6 + PB | 1 | $500,000 | 1 | $0 (jackpot share) | $500,000+ |
| 5 + bonus + PB | 2 | $21,736 | 2 | $47,445 | $69,181 |
| 5 + PB | 3 | $609 | 3 | $1,143 | $1,752 |
| 4 + bonus + PB | 4 | $60 | 4 | $117 | $177 |
| 4 + PB | 5 | $31 | 5 | $61 | $92 |
| 3 + bonus + PB | 6 | $23 | 6 | $43 | $66 |
| 3 + PB | 7 | $0 | 7 | $0 | $0 |
| ≤2 + anything | — | $0 | — | $0 | $0 |

### Bonus Ball Role Summary

- The bonus ball is **never required** for Div 1 (6 mains is enough).
- It **never saves** a ticket — you still need the main matches first.
- It only **upgrades**: 5→Div2, 4→Div4, 3→Div6 when bonus AND PB both match.
- In standard Lotto (no PB), the bonus similarly upgrades Div 3→2, Div 5→4, Div 7→6.
- The bonus ball on its own wins nothing; it only enhances an already-winning combination.

### Recent/Upcoming Changes

- **Lotto Rules 2025** (effective 29 Sep 2025): Core structure unchanged (6/40 + 1/10 PB + bonus). Minor administrative updates.
- **Matrix change proposal**: Lotto NZ has floated increasing PB pool to 12 or 15 balls, which would reduce Division 1 odds from ~1:38M to ~1:46M or ~1:57M and allow larger jackpots. Not yet approved.
- **No changes to the bonus ball role**: The bonus has been part of NZ Lotto since at least 2002 (Lotto Amendment Rules No 2) and its role across divisions is stable.

---

## Improvement Ideas

### 1. Bonus Ball Frequency Chart
Add a bar chart to the dashboard showing the historical frequency of each bonus ball number (1–40). Colour-code hot/cold and overlay the expected frequency line (uniform distribution = 2.5%). This helps players quickly see which bonus numbers appear most/least often.

**Location:** Dashboard — new "Bonus Ball Analysis" tab or section below existing frequency charts.
**Data:** Already in the DB (`bonus` column in `draws`).
**Effort:** Low — pure front-end addition.

### 2. Bonus Ball Hot/Cold Table
Add a dedicated sortable table showing each bonus ball (1–40) with columns: count, frequency %, recency (last drawn date), gap (draws since last appearance), and z-score. Highlight numbers more than 2 standard deviations from the mean.

**Location:** Dashboard or `lotto_wheels.py report` output.
**Data:** Already in the DB.
**Effort:** Low.

### 3. Bonus Ball Prediction Methods
Add 1–2 bonus-ball-specific prediction methods to `predictions.py`:
- **Bonus Bayesian** — Dirichlet-Multinomial posterior for bonus ball only (separate from main numbers).
- **Bonus Gap** — Rank bonus balls by gap z-score + frequency z-score (similar to "Due Numbers" for main numbers).

**Location:** `predictions.py` — new prediction methods, displayed in dashboard.
**Effort:** Medium — new analysis functions.

### 4. Custom Draw — Bonus Match Toggle
On the dashboard's "Check Latest Draw" page, when a user selects a non-latest draw (or enters custom numbers), add a checkbox or toggle to set whether the bonus ball was matched. Current implementation reads `draw_bonus` from the DB, but a manual override would let users explore "what-if" scenarios.

**Location:** Dashboard draw selector / custom draw input.
**Effort:** Low — UI addition + passing the toggle value through `check_all_wheels()`.

### 5. Wheel Bonus Coverage Analysis
Add a metric to each wheel's stats showing its bonus ball coverage — how many of the 40 possible bonus numbers appear across the wheel's pool. A wheel that covers more bonus ball numbers has a higher chance of the bonus upgrade on any given draw.

**Extension:** When running `wheel_generator.py`, add an optional optimization target that maximizes bonus coverage for a given pool size.

**Location:** Dashboard wheel results table + `wheel_generator.py`.
**Effort:** Medium — new metric + optional generator tweak.

### 6. EV Simulation With/Without Bonus
Run Monte Carlo simulations comparing wheel expected value with and without the bonus ball upgrade. This quantifies the value of bonus coverage — e.g., "wheel A has 3.2% higher EV than wheel B because it covers 12 vs 8 bonus numbers."

**Location:** `backtest.py` or a new `ev_simulation.py` script.
**Effort:** Medium-high — new simulation logic.

### 7. Standard Lotto (No PB) Division Tab
Add a dashboard tab showing what each wheel would have won in standard Lotto (without Powerball), using the 7-division Lotto-only structure. Since many draws have no Powerball win, this gives a more complete picture of wheel performance. The Lotto-only divisions use the bonus ball differently (upgrades Div 3→2, 5→4, 7→6 even without PB).

**Location:** Dashboard — new "Lotto Only" results tab.
**Effort:** Medium — new division lookup + display.

### 8. Bonus Ball Pair / Triplet Analysis
Analyze whether certain bonus ball numbers tend to co-occur with specific main numbers. For example, "bonus 10 has appeared with main number 22 in 12% of draws." Use a co-occurrence matrix or association-rule mining.

**Location:** New analysis functions + dashboard heatmap.
**Effort:** Medium-high — new statistical methods.

### 9. Multi-Period Bonus Rotation
Extend `rotation_scheduler.py` to optionally include a recommended bonus ball rotation plan alongside the main-number rotation. Each period could suggest 2–3 bonus balls (e.g., primary, secondary, tertiary) based on Bayesian posterior for bonus balls alone.

**Location:** `rotation_scheduler.py` — new `--include-bonus` flag.
**Effort:** Low-medium — reuse existing Bayesian machinery for the bonus-ball subset.

### 10. Backtest Bonus Impact Report
Extend `backtest.py` output with a "Bonus Impact" section that shows:
- How many tickets were upgraded by the bonus ball (e.g., "15 tickets upgraded from Div 3 to Div 2")
- The total value added by the bonus ball across the backtest period
- The implied "bonus premium" (% of total prize attributable to bonus upgrades)

**Location:** `backtest.py` output section.
**Effort:** Low — tracking counters + display lines in the existing loop.

---

## Sources

- [Lotto Rules 2000 (as at 2015)](https://www.legislation.govt.nz/secondary-legislation/pco-drafted/2001/1/en/2015-02-05/#DLM19765) — Division definitions
- [Lotto Amendment Rules (No 2) 2002](https://portal.zero.govt.nz/8d6481d27fda66744979f611e6bdd2f1/regulation/public/2002/0350/latest/DLM166702.html) — Bonus ball introduction
- [Lotto Amendment Rules 2010](https://portal.zero.govt.nz/8d6481d27fda66744979f611e6bdd2f1/regulation/public/2010/0275/latest/whole.html#DLM3166005) — Current prize pool percentages
- [Lotto Rules 2025](https://legislation.govt.nz/secondary-legislation/pco-drafted/2025/174/en/latest/#LMS1466972) — Upcoming rules (effective 29 Sep 2025)
- [Safer Gambling NZ — How Lotto Works](https://www.safergambling.org.nz/how-gambling-works/how-lotto-works) — Basic odds and mechanics
- [NZCity Lotto Results](https://home.nzcity.co.nz/lotto/lotto.aspx) — Division percentage estimates
- [MyLotto API](https://pathway.mylotto.co.nz/api/results/v1/results/lotto) — Live payout data (used in `prize_calculator.py`)
