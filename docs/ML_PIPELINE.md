# ML Pipeline — Predictions & Model Freshness

How the Lotto Wheel App turns historical NZ Lotto Powerball draws (6 mains
1–40, bonus 1–40, Powerball 1–10) into predictions, how those predictions are
scored, and how models stay current.

## Data flow

```
MyLotto API ──> update_draws.py ──> lotto.db (draws table)
                                        │
                    ┌───────────────────┼────────────────────────┐
                    ▼                   ▼                        ▼
            predictions.py      train_ml_model.py          ensemble.py
   (frequency / Bayesian /   → feature engineering      (EnsemblePredictor,
    gap / hierarchical /      → XGBoost classifiers      walk-forward weights)
    XGBoostPredictor)         → model.pkl
                    │                   │                        │
                    └───────────────────┼────────────────────────┘
                                        ▼
                            FastAPI endpoints (api.py)
                     POST /predictions, GET /predict/*, /leaderboard
                                        ▼
            Streamlit dashboard pages (ML Predictor, 📊 Predictor Leaderboard)
```

`update_draws.py` fetches results from the MyLotto API with retry/backoff
(HTML and Selenium fallbacks; check with `python update_draws.py --check-selenium`)
and upserts into the `draws` table of `lotto.db` (columns include
`draw_date, n1..n6, powerball, bonus`). Every predictor reads from that table —
there is no separate feature store.

## Predictors

All predictors in `predictions.py` consume draw tuples
`([n1..n6], powerball, bonus, draw_date)` and return ranked numbers plus
probability or score estimates.

### Frequency baseline

- `predictions.frequency(draws)` — picks the 6 most common main numbers and
  most common Powerball across all history.
- The API's `method="frequency"` uses counts over the **last 30 draws**
  (`_frequency_probs(last_n=30)` in `api.py`).

### BonusBayesian (Dirichlet-Multinomial)

`BonusBayesian(bonus_balls, alpha=1.0)` fits a symmetric Dirichlet prior over
bonus balls 1–40. Posterior for number *i* is
`(count_i + alpha) / (total + 40 * alpha)`. `predict_top_k(k)` returns
`[(bonus_number, probability), ...]` sorted descending.

### Gap method

`bonus_gap_prediction(conn, k=5)` reads `bonus, draw_id` from the `draws`
table and combines a **gap z-score** (draws since last appearance) with a
**frequency z-score**: `combined = 0.5 * gap_z + 0.5 * freq_z`. Returns the k
lowest-scoring (most "due") numbers as `[(bonus_number, score), ...]`.

### HierarchicalBonusPredictor (recency half-life)

`HierarchicalBonusPredictor(draws, smoothing=1.0, recency_halflife_days=90)`
takes `(draw_date, bonus)` pairs and applies exponential recency decay:
each draw's weight is `2 ** (-days_ago / halflife)`. The weighted counts feed a
Dirichlet-Multinomial posterior; `fit()` computes `posterior_mean` and
`posterior_std` per number, and `predict_top_k(k)` returns
`[(bonus_number, mean, std), ...]`. A shorter half-life makes the posterior
more reactive to recent draws.

### XGBoost + SHAP

Two entry points share the same idea — one binary classifier per number range
(features computed only from past draws; no leakage):

- **`train_ml_model.py`** (offline training) builds 17 features per number per
  draw — normalized number, frequencies over 10/30/all draws, normalized gap,
  lag-1/2/3 indicators, rolling means, average/most-common position, max
  streak, decade, odd/even, co-occurrence with hot numbers — and trains
  `XGBClassifier` models (500 estimators, early stopping, chronological 80/20
  split) for mains (1–40) and Powerball (1–10). Everything is pickled to
  **`model.pkl`** along with feature names, date range, and test AUC.
- **`predict_ml.py`** loads `model.pkl`, rebuilds features for the *next* draw
  (the feature builder must match training exactly), and prints ranked
  numbers with probabilities.
- **`predictions.XGBoostPredictor`** is the in-app variant used by the
  dashboard's **ML Predictor** page: 6 features (`freq_last_1/3/5`,
  `recency_days`, `cold_streak`, `rolling_avg_10`) plus a cyclic number index,
  trained on the most recent 200 draws, with SHAP `TreeExplainer` support
  (force plots per number, summary plot saved to `data/plots/shap_summary.png`).

### EnsemblePredictor (walk-forward weight calibration)

`ensemble.EnsemblePredictor(conn)` fuses four sub-predictors from
`predictions.py` — `frequency`, `bayesian`, `markov`, `due_numbers`.
`fit_weights(validation_draws=10)` walks forward over the last 10 draws:
each sub-predictor is retrained on all preceding draws, scored with a Brier
score against the actual outcome, and weights are set proportional to inverse
Brier (softmax-normalised, tracked in `weight_history`).
`predict_main_numbers(top_n=15)` returns the weighted-average probabilities;
`predict_all(main_top, bonus_top, pb_top)` adds bonus picks from
`HierarchicalBonusPredictor` (90-day half-life) and frequency-based Powerball
picks, plus the calibrated `ensemble_weights`.

### steps/ pipeline modules

The `steps/` package is a composable feature/probability pipeline that builds
a unified 50-element probability vector (40 mains + 10 Powerballs):

| Module | Role |
|---|---|
| `historical.py` | Validate/filter raw draws into the pipeline |
| `frequency.py` | Normalized frequency for mains + Powerball |
| `decay.py` | Draw-based (not time-based) recency decay weighting |
| `bayesian_fusion.py` | Log-space fusion of frequency + decay + mechanics bias (chi-square gate; collapses to uniform if not significant) |
| `markov.py` | First-order cluster→cluster transition features |
| `clustering.py` | K-Means on fused probabilities |
| `entropy.py` | Shannon entropy per number (`-p·log2 p`) |
| `redundancy.py` | Recency + unbiased gap features, variance-normalized |
| `monte_carlo.py` | Monte Carlo simulation of adjusted probabilities |
| `deep_learning.py` | Deep-learning prediction step over stacked features |
| `generate_ticket.py` | Ticket selection with soft repetition penalty and anti-overlap rejection sampling |

## API contract

### `POST /predictions`

Request body (`PredictionRequest` in `api.py`):

```json
{ "method": "ensemble", "top_k": 12 }
```

- `method`: one of `frequency` (last-30-draw counts), `ml` (requires
  `model.pkl`; 501 if missing), `ensemble` (same internals as
  `GET /predict/ensemble`).
- `top_k`: 1–40, default 20.

Response: ranked `numbers`, parallel `probabilities` (0–1, 6 dp),
`method_used`, and `generated_at`. Returns 404 when no draw data exists.

```bash
curl -X POST http://localhost:8000/predictions \
  -H "Content-Type: application/json" \
  -d '{"method": "ensemble", "top_k": 10}'
```

### `GET /predict/*`

| Endpoint | Params | Returns |
|---|---|---|
| `/predict/bonus_bayesian?k=5` | k ≤ 40 | rank, bonus_number, probability |
| `/predict/bonus_gap?k=5` | k ≤ 40 | rank, bonus_number, score |
| `/predict/bonus/hierarchical?k=5&halflife=90` | k ≤ 40, halflife days | rank, bonus_number, posterior_mean, posterior_std |
| `/predict/bonus/probability?num=7&halflife=90` | num 1–40 | posterior mean/std for one number |
| `/predict/ensemble?main=15&bonus=5&pb=3` | top counts | main/bonus/powerball lists + ensemble_weights; cached 5 min (Redis or in-memory) |

Standard rate limits apply (anonymous 10/min, authenticated 60/min; 429
responses carry `Retry-After`).

## Evaluation

`accuracy_tracker.py` stores every prediction in `prediction_records` and,
once the real draw lands (`backfill_actuals`), builds per-predictor
`ScoreCard`s over rolling windows of 10/20/50 draws:

- **Hit rate** — fraction of drawn numbers covered by the recommendation.
- **Brier score** — mean squared error of the 40-number probability vector.
- **Top-k accuracy** — did any drawn number appear in the top 10/15/20?
- **MRR** — reciprocal rank of the first recommended number that was drawn.
- Exact-match counters for ≥3/4/5/6 of the top-6 picks.

`update_all_scorecards()` refreshes all predictors × windows; results are
served by `GET /leaderboard` (ranked by hit rate, then top-15 accuracy, then
Brier) and visualised on the dashboard's **📊 Predictor Leaderboard** page,
which also offers a **🔄 Refresh Scores** action.

## Retraining schedule

Recommended: **retrain weekly, or after each new draw is imported** (draws run
twice a week, Wednesday and Saturday).

- `python update_draws.py` (optionally `--date` / `--range`) keeps the `draws`
  table current; `python scheduler.py --daemon` runs Thursday and Sunday 8am
  to fetch the latest result, check stored tickets, and fire win alerts. These
  jobs keep **data** fresh — they do not retrain models automatically.
- Retraining is a manual step:

```bash
python train_ml_model.py --db lotto_working.db --output model.pkl
python predict_ml.py --model model.pkl --db lotto_working.db --top 10
```

  If your CPU lacks AVX, run `train_ml_model.py` on Google Colab (a full
  copy-paste guide is embedded at the bottom of the script) and download the
  resulting `model.pkl`.
- The API's `ml` method reads `model.pkl` from the repo root per request, so
  replacing the file takes effect immediately — no restart needed.
- The dashboard's **ML Predictor** page caches its in-session
  `XGBoostPredictor` keyed by a hash of the last 200 draws; it only re-fits
  when new draw data changes that hash.
- `GET /predict/ensemble` responses are cached for 5 minutes because the
  walk-forward fit is expensive.

## Limitations

- **Lotto draws are independent random events.** No predictor here — or
  anywhere — can change the underlying odds. AUC in the 0.57–0.60 range seen
  in training is expected for near-random data.
- **Probabilities are descriptive, not predictive guarantees.** A "12%"
  estimate means the model assigns that share based on historical patterns;
  every combination still has the same true probability of being drawn.
- **Hot/due/gap heuristics have no causal basis** ("gambler's fallacy"); they
  are provided for analysis and entertainment, and the leaderboard exists
  precisely so you can see how each method actually performs over time.
- **No edge is promised.** Use these tools to explore the data and structure
  tickets (e.g. with wheels), not as a basis for spending decisions.
