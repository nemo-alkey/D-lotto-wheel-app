# Mathematical Guarantees — Wheeling Systems Explained

This page explains, in plain language, what the Lotto Wheel App means when it says a wheel
has a *guarantee*. No mathematics background is needed.

> **Important up front:** a guarantee is a promise about the *worst case* of your tickets,
> not a promise of profit. See [A guarantee is not profitability](#a-guarantee-is-not-profitability).

## The basic idea

New Zealand Lotto draws **6 main numbers from 1–40** (plus a bonus ball 1–40 and a
Powerball 1–10). A single ticket has 6 numbers.

Suppose you like **10 numbers** — say your birthdays, "hot" numbers, whatever. There are
**210** different ways to pick 6 of those 10 (`C(10,6) = 210`). Playing all 210
combinations is called a **full wheel**, and it guarantees that *if* all 6 winning numbers
are among your 10, one of your tickets matches all 6. The catch: at $1.50 per Powerball
line, that's **$315 per draw**.

A **wheeling system** (also called an *abbreviated wheel* or, in mathematics, a
**covering design**) is a carefully chosen subset of those combinations that keeps a
smaller, useful promise at a fraction of the cost. The built-in `single1` wheel, for
example, plays only **20 of the 210** combinations — **$30 instead of $315** — and still
guarantees that if any 4 of your 10 numbers are drawn, at least one of your tickets
matches 4 or more.

What you give up is the top-end certainty: an abbreviated wheel no longer guarantees the
jackpot if all 6 of your numbers come up. You trade a very expensive absolute guarantee
for a cheap, weaker one.

## The "X if Y" notation

Every wheel in the app is described as **"X if Y"**:

- **Y** — the *trigger*: how many of the 6 drawn numbers must come from your chosen pool.
- **X** — the *guarantee*: if the trigger happens, at least one ticket is guaranteed to
  match at least X numbers.

So **"4 if 4"** reads: *if 4 of the drawn numbers are in your pool, at least one ticket
has 4+ matches.* The guarantees are statements about the tickets only — they say nothing
about how likely the trigger itself is. The drawn numbers are still random.

## The built-in wheels

The app ships five wheels from Iliya Bluskov's book *Combinatorial Lottery Systems
(Wheels) with Guaranteed Wins*, hardcoded in `lotto_wheels.py`:

| Wheel | Pool | Tickets | Cost @ $1.50 | Guarantee (as validated by the app) |
|---|---|---|---|---|
| `single1` | 10 numbers | 20 | $30.00 | 4 if 4 — at least **one** 4-win if 4 of your pool are drawn |
| `single2` | 10 numbers (different set) | 20 | $30.00 | 4 if 4 — same guarantee, second number set |
| `double` | 10 numbers | 30 | $45.00 | 4 if 4 (**double**) — at least **two** 4-wins if 4 are drawn (Bluskov System #88) |
| `five-if-six` | 11 numbers | 22 | $33.00 | 5 if 6 — a 5-win if **all 6** drawn numbers are in your pool |
| `jackpot7` | 7 numbers | 7 | $10.50 | 6 if 6 — the **jackpot** if all 6 drawn numbers are in your pool |

Notes:

- `jackpot7` is actually a full wheel: `C(7,6) = 7`, so all combinations of its 7 numbers
  are played. It's the only built-in wheel whose top prize is guaranteed under its trigger.
- Each wheel also suggests a fixed Powerball number (3 for most, 6 for `single2`).
- The trigger is the hard part. For "5 if 6" and "6 if 6", *every one* of the 6 drawn
  numbers must be inside your small pool — a rare event. The guarantee is real; the
  trigger is unlikely.

List or inspect them from the command line:

```bash
python lotto_wheels.py list-wheels
python lotto_wheels.py show-wheel single1
python lotto_wheels.py check single1 "2,9,12,21,28,39" 3
```

## A worked example (single1)

`single1` plays these 10 numbers: **9, 11, 12, 14, 17, 18, 28, 38, 39, 40** across
20 tickets. Suppose the draw is:

```
Drawn: 2  9  12  21  28  39   (Powerball 5)
```

Four of the drawn numbers — 9, 12, 28, 39 — are in the pool, so the trigger is met.
Ticket 10 of the wheel is:

```
Ticket 10:  9  12  28  38  39  40
```

It matches **9, 12, 28, 39** — 4 matches, a Division 5 hit (the app's payout table
estimates ≈ $60). The guarantee says this outcome (or better, on some ticket) happens for
*every* possible draw that contains any 4 pool numbers — not just this one. If only 3 of
your pool numbers are drawn, the guarantee simply doesn't apply; you may still win smaller
prizes, but nothing is promised.

## Custom wheels and pair coverage

Beyond the five built-ins, `wheel_generator.py` builds abbreviated wheels on the fly for
any pool of **6–20 numbers** with guarantees such as "4 if 4", "4 if 5", or "5 if 6".
It uses a set-cover heuristic: start from all `C(pool,6)` combinations and greedily keep
the tickets that cover the most not-yet-covered trigger combinations.

The API endpoint `POST /wheels/generate` exposes this. If you don't supply
`user_numbers`, the pool is picked from the hottest numbers of the last 30 draws:

```bash
curl -X POST http://localhost:8000/wheels/generate \
  -H "Content-Type: application/json" \
  -d '{"pool_size": 10, "guarantee_type": "4 if 4"}'
```

The response includes the tickets plus coverage statistics:

```json
{
  "tickets": [[1, 3, 7, 11, 19, 22], [1, 7, 27, 33, 35, 40]],
  "system_used": "If 4 of your 10 numbers are drawn, you are guaranteed at least one ticket with 4+ matches.",
  "coverage_stats": {
    "pair_coverage_pct": 73.33,
    "ticket_count": 7,
    "pool_size": 10,
    "guarantee": "4 if 4"
  }
}
```

**Pair coverage** is a useful secondary quality measure: of all `C(pool,2)` pairs of pool
numbers, what percentage appear together on at least one ticket? A wheel can honour its
"X if Y" guarantee while still leaving some pairs uncovered — `pair_coverage_pct` tells
you how evenly the wheel spreads your numbers. Higher is generally better for picking up
small prizes, but it is *not* part of the formal guarantee.

## How the app verifies the guarantees

You don't have to take the guarantee on faith. `wheel_validator.py` re-checks each
built-in wheel by **Monte Carlo simulation**: it draws thousands of random triggers from
the pool (e.g. 10,000 random sets of 4 numbers for a 4-if-4 wheel), scores every ticket
against each draw, and confirms the promise always held. It reports:

- `claimed_guarantee` / `passed` — the claim and whether it survived every simulation;
- `coverage_ratio` — fraction of simulated triggers where the guarantee held (should be 1.0);
- `worst_case_match` — the worst best-ticket seen across all simulations;
- a **pair-coverage matrix** showing how many tickets contain each pair of pool numbers.

Two ways to see it:

- **Dashboard:** open the Streamlit app (port 8501) → **Wheel Explorer** page. Pick a
  wheel, choose the number of simulations (up to 100,000), and click **Run Validation**
  to get a pass/fail badge and a pair-coverage heatmap.
- **API:** the `coverage_stats` in the `POST /wheels/generate` response above.

## A guarantee is not profitability

This is the part that matters most. A wheel guarantee means: *when the trigger occurs,
you will win at least a certain small prize.* It does **not** mean you win money on
average:

- **The trigger is rare.** For "4 if 4" with a 10-number pool, 4 specific-drawn numbers
  landing inside your pool happens only occasionally; most draws the guarantee is moot.
- **The guaranteed prize is small.** A guaranteed 4-win (≈ $60 in the app's estimate
  table) against $30–$45 of tickets per draw, collected only when the trigger fires,
  does not cover long-run spend.
- **Expected value is still negative.** Every lottery ticket returns less, on average,
  than it costs. Wheeling rearranges *how* your tickets win; it does not change the
  underlying odds of the draw. No wheel, prediction model, or feature of this app can do
  that.

Play wheels because they make a fixed budget more interesting and smooth out small wins —
never spend more than you can comfortably afford to lose. If gambling stops being fun,
contact the NZ Gambling Helpline (0800 654 655) or your local support service.

## Credits

The built-in wheels are published combinatorial designs by **Iliya Bluskov**, from
*Combinatorial Lottery Systems (Wheels) with Guaranteed Wins*. Additional designs
(System #88 and others) live in `bluskov_wheel_library.py`.

## See also

- `lotto_wheels.py` — built-in wheels, payout table, CLI (`show-wheel`, `check`, `export`)
- `wheel_generator.py` — custom abbreviated wheels for 6–20 number pools
- `wheel_validator.py` — Monte Carlo guarantee validation and coverage matrices
- Dashboard **Wheel Explorer** page and `POST /wheels/generate` for interactive stats
