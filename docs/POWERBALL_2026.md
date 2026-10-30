# Powerball 2026 rule change

Reference for the September 2026 NZ Powerball change and how the codebase handles it.

---

## What changed

Effective 2026-09-16 (first new-rules draw):

| Aspect | Before | After |
|---|---|---|
| Powerball pool | 1-10 | 1-14 |
| Division 1 odds per line | 1 in 38.4M | 1 in 53,737,320 |
| Division 7 fixed | $15 | $20 + 4 bonus lines |
| Division 8 | (did not exist) | $12 fixed |
| Jackpot range | $5M to $60M | $5M to $60M (unchanged) |

Division 8 rule (Lotto Amendment Rules 2026, SL 2026/51, rule 30(1)(h)):

> A ticket matching 2 main numbers + the bonus number + the Powerball wins Powerball Division 8, $12 fixed.

---

## The era model

Every draw is classified into one of two eras:

- pre_2026_09_16 - draw_date before 2026-09-16, Powerball pool is 1-10
- post_2026_09_16 - draw_date on/after 2026-09-16, Powerball pool is 1-14

The rule_era column on the draws table stores this classification. It is populated automatically by ingestion.

### Historical pool sizes

The full Powerball pool history has three phases:

| Era | Dates | Pool |
|---|---|---|
| Launch | 2001-08-01 to 2007-12-31 | 1-8 |
| Middle | 2008-01-01 to 2026-09-15 | 1-10 |
| 2026 change | 2026-09-16 onward | 1-14 |

The 2001-2007 pool of 1-8 is a verified historical fact
(`scripts/analysis/verify_pool_change.py`): a chi-square over the full
pre-2026 history shows a PB 9/10 deficit (p=0.0001), but restricting to
2008+ is uniform over 1-10 (p=0.54). It is not tracked as a separate
`rule_era` value; it is a property of `draw_date` and matters only for
historical statistics.

---

## Source of truth: powerball_rules.py

Every era-scoped decision goes through this module.

Constants:

    POWERBALL_CHANGE_DATE = date(2026, 9, 16)
    POWERBALL_MAX_OLD = 10
    POWERBALL_MAX_NEW = 14

Functions:

| Function | Purpose |
|---|---|
| parse_draw_date(value) | Parse ISO strings and page formats; raises on unparseable |
| powerball_max_for_date(draw_date) | Return 10 or 14 depending on era |
| validate_powerball(pb, draw_date) | Raise ValueError if out of range for the era |
| pb_fixed_prizes(draw_date) | Return dict for the era (Div 7 and Div 8 amounts) |

### Why no None shortcut

Earlier code attempted powerball_max_for_date(None) to mean "current rules". That is not supported - the function requires a real date. For "current rules" callers should import POWERBALL_MAX_NEW directly.

---

## Era guard: era_features.py

Mixed-era Powerball training produces a model that fits nothing. The guard makes this impossible to do by accident.

    from era_features import check_single_era, MixedEraTrainingError

    try:
        check_single_era(draws, era_aware=False)
    except MixedEraTrainingError as e:
        # training data spans both eras; fix it or opt in explicitly
        ...

Opt-in (caller supplies era as a feature):

    check_single_era(draws, era_aware=True)

Function reference:

| Function | Purpose |
|---|---|
| rule_era_for_date(date) | Return pre_2026_09_16 or post_2026_09_16 |
| powerball_pool_size(date) | Alias for powerball_max_for_date |
| filter_draws_by_era(draws, era) | Filter dicts or tuples to one era |
| check_single_era(draws, era_aware=False) | Raise if data spans both eras |
| era_flags(draws) | Return per-draw 0/1 for pre/post |
| powerball_training_draws(draws) | Return current-era-only draws |

---

## What was fixed

The rule change touched a lot of code. The changes fell into four groups:

1. Ingestion. Scrapers previously clamped out-of-range Powerball values to 0 rather than raising. Silent clamping was the root cause of 104 corrupted rows in lotto.db. Fixed by validating through validate_powerball everywhere.

2. Prize engine. resolve_divisions treated any ticket with fewer than 3 main matches as a loss. With Division 8 introduced, that assumption is wrong for post-change draws. Fixed by adding the Div 8 case with era awareness.

3. Data repair. 104 rows had powerball=0 due to legacy clamps. 710 rows have legitimate powerball=0 because they predate the Powerball launch in August 2001. repair_powerball_zero.py distinguishes these two cases.

4. Hardcoded pool assumptions. 21 sites in 9 files hardcoded Powerball range 1-10 (or range(1, 11)). All replaced with the era-aware constant.

---

## Common pitfalls

Do not hardcode 10 or 14. Always import from powerball_rules. Searching for range(1, 11) or NUM_POWERBALL = 10 should return nothing in executable code.

Do not mix eras in PB training. check_single_era guards against this; do not bypass it without supplying the era as a feature.

Do not assume PB > 0. Pre-2001 draws legitimately have powerball=0. Distinguish "no Powerball era" from "missing data" by checking the draw date, not the value.

Do not use powerball_max_for_date(None). It raises. Use the POWERBALL_MAX_NEW constant for "current rules".

---

## Working with the era boundary in tests

Tests that touch Powerball should be explicit about the era:

    from powerball_rules import POWERBALL_CHANGE_DATE

    PRE_CHANGE_DATE = "2026-09-12"
    POST_CHANGE_DATE = "2026-09-16"

The test fixture db_connection in tests/conftest.py creates a draws table with the current schema (including rule_era and draw_number), so new tests can rely on the era column being present.