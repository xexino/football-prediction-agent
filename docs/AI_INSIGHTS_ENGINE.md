# AI Match Insights — Engine B

Engine B is an **independent** prediction engine and match analyst. It was built from scratch with its own features, models,
records, bankroll and evaluation. Engine A (the original Dixon-Coles + Elo engine) is unchanged:
* its modules have no diff from the pre-Engine-B `main`;
* a golden-value regression test (`test_engine_a_outputs_unchanged`) pins its numbers;
* `test_engine_b_never_touches_engine_a_records` proves Engine B never writes Engine A's tables.

The concept is inspired by match-insight products such as SofaScore AI Insights. No proprietary code, private endpoints
or undisclosed models are used.

## Separation
| | Engine A | Engine B |
|---|---|---|
| Code | `fil/models`, `fil/pipeline.py`, `fil/value.py`, `fil/betting.py` | `fil/engine_b/*`, `fil/api_b.py` |
| Tables | `predictions`, `value_assessments`, `virtual_bets`, `settlements`, `bankroll_transactions` | `eb_predictions`, `eb_bets`, `eb_settlements`, `eb_bankroll_transactions`, `eb_evaluations`, `eb_live_snapshots`, `eb_live_events`, `eb_model_versions`, `eb_validation_runs` |
| Bankroll | €100, €1 flat, conservative | **separate** €100, €1 flat, medium risk |
| Job steps | critical (settle, predict) | all **non-critical**: an Engine B failure can never fail Engine A's run |
| Immutability | SQLite triggers | SQLite triggers on all Engine B ledger and prediction tables |

## Features (`engine_b/features.py`)
One chronological pass computes, for every match, the values known **before** kickoff. The state is updated only after
the row is emitted (`test_features_are_strictly_pre_match`). The features are:
* per team, exponentially weighted (α = 0.12, roughly an 8-match memory), "for" and "against": goals, shots on target,
  corners, yellow cards, fouls, shots; plus goals at home and away;
* per competition: running league means, split home and away;
* Engine B's own Elo (K = 18, home advantage 55; Engine A uses 20 and 65);
* rest days;
* league red-card rate.

## Models (`engine_b/model.py`, version `eb-insights 1.0.0`)
* **Count models:** goals, corners, yellows, shots on target, shots and fouls each use a home and an away **Poisson GLM**
  (scikit-learn `PoissonRegressor`, α = 1e-3). Inputs: attack EWMA ratio, opponent defence EWMA ratio, Elo gap,
  league mean, rest days; goals also use shots-on-target attack and defence. Training uses a 1,100-day window and teams
  with at least 6 prior matches.
* **Goals:** a score matrix with a Dixon-Coles low-score correction ρ, fitted by maximum likelihood (currently −0.05).
* **Totals of corners, cards, shots and fouls:** negative binomial, with dispersion estimated on the training set.
* **Red cards:** the league base rate only, labelled as such. Team-level modelling would not be statistically defensible.

## Markets produced
* **Goals and result:** 1X2; double chance; BTTS; Over/Under 0.5–4.5 goals; expected home, away and total goals; top 8
  correct scores; full 8×8 score matrix; clean sheets; first team to score (Poisson-process assumption, stated).
* **Corners:** expected (home, away, total, 80% interval); Over 7.5, 8.5, 9.5, 10.5; team Over 3.5, 4.5, 5.5; team
  distributions 0–12.
* **Cards:** expected yellows; Over 2.5, 3.5, 4.5; team Over 0.5, 1.5, 2.5; any red card (league rate).
* **Shots, shots on target, fouls:** expected values, 80% intervals and Over lines.
* **Unavailable, and shown as unavailable:** player shots, goals and assists; offsides; goal timing; possession. These
  need API-Football or a paid provider.
* Any market whose statistics are missing for a competition (e.g. corners in Argentina) is **unavailable**, never zero.

## AI Match Analyst (`engine_b/insights.py`)
* Deterministic templates over model outputs and stored data. Each report contains:
  * overall assessment; goals; corners (with the validation caveat); cards; recent form; head to head (labelled "not a
    model input"); league table; rest; confidence;
  * what supports the prediction;
  * what could make it wrong (model, Engine A and market disagreement);
  * missing or unreliable information.
* It never asserts injuries, lineups or events. Their absence is listed under "missing".
* No LLM key is configured, so no LLM is used. If one is added later it may only rephrase `sections`; it must never
  change numbers.

## Confidence and data quality
* **Data quality (0–100):**
  * history depth: 30
  * shot statistics: 20
  * corner and card history: 10
  * odds: 15
  * league table: 5
  * recency: 10
  * league volume: 10
  * team news: 0 (no source)
* **Confidence (0–100), separate from probability:** 30% data quality, 25% sample size, 25% agreement with Engine A,
  20% Engine B's validated skill in that competition (latest validation run).

## Prediction records
`eb_predictions` stores:
* model version and data cutoff;
* fixture and prediction timestamp;
* every market and the score matrix;
* the full **feature snapshot**, including the odds snapshot IDs used;
* confidence, quality, the unavailable list and the report;
* an inputs hash.

Rows are immutable. Material changes create a new revision row. Unchanged inputs create nothing.

## Virtual bankroll (`engine_b/betting.py`)
* €100 start, €1 flat stake, at most 2 selections per match, €10 daily exposure.
* Conservative probability = 0.25·model + 0.75·market. The edge must be ≥ +3%.
* Odds between 1.40 and 6.00, quality ≥ 60, confidence ≥ 50, model/market gap ≤ 20 pp.
* **Data-error filters:** the reference book's margin must be plausible, and the bookmaker must agree with the reference.
* **1X2 selections are disabled by evidence.** In walk-forward validation, 470 1X2 bets returned ROI −23.5% with a 95% CI
  of [−36.7%, −9.8%]. Only Over/Under 2.5 selections remain; their result is inconclusive.
* No Martingale, no forced bets, NO BET is normal. Settlement uses the same verified-result rules as Engine A, applied to
  Engine B's own tables.
