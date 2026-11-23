# Agent 3 — Machine Learning and Quantitative Modelling Specialist

Reviewed commit `3a1ead6`. Evidence comes from the code, from the read-only production snapshot (`prod.db`), and from my own paired walk-forward re-run on a **copy** of the snapshot (`agent03_tmp/copy.db`; scripts are `agent03_tmp/verify.py` and `agent03_tmp/analyze.py`; per-match output is `agent03_tmp/recs.json`; runtime 151 s). All paths are under `/tmp/claude-0/-home-user-football-prediction-agent/30511605-6d1c-5e9c-bce7-4f2d0ad13976/scratchpad/council/`.

## 1. Current situation
* **Engine A** combines two models: a per-league time-decayed Dixon-Coles model with a ridge prior and an xG blend, and a global goal-difference Elo fed through an ordered logit. They are mixed 0.6/0.4 (`models/engine.py:22-28,110-113`). Derived markets come from rescaling the score matrix (`markets.py:9-19`).
* **Engine B** is a set of feature-based Poisson GLMs built on EWMA team statistics plus its own Elo (`engine_b/features.py`, `engine_b/model.py`). Count totals use a negative-binomial distribution.
* **Both engines are clearly worse than the de-vigged pre-match market on 1X2.** Engine A is better than Engine B on 1X2. Engine B is better than Engine A on O/U 2.5, but still worse than the market there.
* **Neither betting strategy shows an edge.**

**I reproduced the Engine B validation claim exactly** on 4,845 identical matches (4,844 that have a market price):

| 1X2, n = 4,844 | Log loss | ECE |
|---|---|---|
| Engine A | 0.9949 | 0.0119 |
| Engine B | 0.9999 | 0.0156 |
| Market | 0.9819 | 0.0098 |
| Average of A and B | 0.9941 | 0.0118 |

| Paired bootstrap, 4,000 resamples | Mean ΔLL | 95% CI |
|---|---|---|
| B − A | +0.0051 | [+0.0005, +0.0096] — B is significantly worse |
| A − M | +0.0130 | [+0.0079, +0.0179] |
| O/U 2.5: B − A | −0.0054 | [−0.0099, −0.0008] — B significantly better |
| O/U 2.5: B − M | +0.0045 | [+0.0002, +0.0086] — B significantly worse than the market |

## 2. Evidence from the repository
* **Stored Engine A run vs the docs.** `backtest_runs` holds a single row (id 1, 2026-11-22 21:23). Its contents:
  * n = 4,859; ensemble log loss 0.9947; market 0.9817;
  * strategy: **65 bets, ROI −22.0%**, 1X2 30 bets at −33.8%;
  * `ensemble_weight_scan`: w_dc = 0.4 → 0.9942 vs the deployed 0.6 → 0.9947.

  `docs/MODEL_VALIDATION.md:5-46` reports n = 4,861, ROI −25.2% and 29 1X2 bets, plus `by_season`, `by_probability_range`, ECE and `calibration_check` figures. **None of those keys exist in the stored row.** The documented numbers therefore come from a run that is not in production, and `eb_validation_runs` = 0.
* **Calibration (stored row).**
  * Over-confident at 0.4–0.6: predicted 0.4465 vs observed 0.4298, and 0.545 vs 0.5255.
  * Under-confident above 0.6: 0.6453 vs 0.6962, 0.7471 vs 0.7857, 0.8334 vs 0.8854.
  * The pattern is S-shaped, which a single power parameter cannot fix.
* **Coverage gap.** 4,978 finished target matches; 4,845 are scored by both engines.
  * Engine B dropped 91: it needs ≥ 6 matches per team, `features.py:27`, `model.py:283`.
  * Engine A dropped 58: `DCParams.rates` returns `None` for a team that has no in-league matches inside the 1,100-day window (`dixon_coles.py:34-35`, `engine.py:102-104`).
  * The dropped matches are mostly promoted teams. That is selection bias, because they are the hardest matches to predict.
* **Promotion handling.**
  * Engine A, Elo: re-seeds a team at the 20th/80th percentile of its new league, but only inside `update()` at the team's first match (`elo.py:24-37`). That first match is therefore predicted with the stale rating from the other league.
  * Engine A, Dixon-Coles: newcomers get a −0.15/+0.15 prior if they have fewer than 8 recent matches (`dixon_coles.py:147-149`). The prior disappears abruptly at 8 matches.
  * Engine B: no promotion handling at all. EWMA statistics from the old league are normalised by the new league's mean (`features.py:89-90`), and its Elo pools all leagues starting from 1500.
* **Hyperparameters were never tuned.** `xi = 0.0019`, `ridge = 2`, `w_dc = 0.6`, `elo_k = 20`, `home_adv = 65` are hard-coded (`engine.py:22-24`). There is no tuning code.
  * Home advantage is per league in Dixon-Coles (one fit per competition) but global in Elo, at 65.
  * The ordered-logit draw thresholds are pooled across all leagues (`engine.py:79-81`).
* **The market shrink in `value.py:101` means the model barely matters.**
  * With w = 0.10, the conservative probability is p_c = 0.1·p + 0.9·q.
  * The gap cap is |p − q| ≤ 0.15 (`config.py:48-52`), so p_c ≤ q + 0.015.
  * A bet therefore needs a Bet365 price of at least 1.02 / (q + 0.015), which is close to the reference fair price 1/q.
  * In practice the rule selects price differences between bookmakers, and the model has little influence. That is consistent with positive CLV alongside negative ROI.
* **Engine B's shrink weight was not derived from data.** It uses w = 0.25 (`betting.py:26`), and nothing in the repository derives that value.
* **CLV is measured against the wrong closing price.** It is computed against the *same* bookmaker's closing price (`backtest.py:176`, `validation.py:134-139`, `betting.py:163-171`), not against a de-vigged sharp closing price (BFE/PS).
* **Engine B validation does not test the live rules.**
  * Its strategy loop hard-codes `quality = 80` and `confidence = 70` (`validation.py:130`), so the live gates are bypassed.
  * Because `RISK.markets = ("OU25",)`, the documented result of 470 1X2 bets cannot be regenerated with the current code.
* **The two engines are not compared on equal terms.** Inside each 14-day step:
  * Engine B's features keep updating match by match, because rows are built in one chronological pass.
  * Engine A's parameters stay frozen at the step date.
  * This slightly favours Engine B, which is still worse on 1X2.
* **No leakage found.**
  * Engine A training uses `kickoff < ref_date` (`engine.py:64`), and the ordered logit is fitted on pre-match Elo differences.
  * Engine B emits each row's features before updating its state (`features.py:158-165`; test at `tests/test_engine_b.py:56-68`).
  * Strategies use pre-match odds; closing odds are used only for CLV.
  * There is no equivalent leakage test for Engine A's `Engine.build`.
* **The live model** (`live.py:213-234`) is basic:
  * remaining goals are uniform-rate Poisson over 94 minutes;
  * red-card multipliers are fixed (0.75 / 1.20) and apply for the whole remaining time;
  * there is no Dixon-Coles correction and no effect from the current score.

  It has **never been validated**: `eb_live_snapshots` = 0 rows, and football-data.org's free plan provides no match minute, so no live probabilities are ever produced.

## 3. What is working well
* The walk-forward framework is honest. Training is strictly time-aware and refit every 14 days, predictions are immutable, and models are compared with baselines and the market on identical matches.
* The Dixon-Coles implementation is sound: analytic gradient (tested in `test_dixon_coles_gradient_matches_numeric`), power de-vig, and a fitted rho.
* Corners were correctly labelled "no skill" (MAE 2.730 vs 2.723), and red cards use only a base rate. This is honest scoping.
* Calibration was tested and correctly *not* deployed. My paired check agrees:
  * Engine A, t = 1.021: ΔLL −0.0002, CI [−0.0005, +0.0001].
  * Engine B, t = 0.899: ΔLL +0.0001, CI [−0.0017, +0.0019].
* The market shrink weight for Engine A is chosen by log loss, not by profit. My log-pool fit agrees: market weight 0.88, model weight 0.13.

## 4. What is weak or missing
* **The gap to the market is largest in ENG2, ESP1, FRA1 and ITA1.** Engine A − market ΔLL ranges from +0.019 to +0.028, all with CIs excluding 0. In BEL1, NED1, POR1 and SCO1 the gap is within noise.
* **Low-history matches** (fewer than 25 team matches, n = 174): Engine A − market = +0.024, CI [−0.004, +0.054]. This is a weak signal that promotion and newcomer handling costs accuracy.
* **Stacking with the market does not help yet.** I fitted a log-linear pool on the first half and tested it on the second half:
  * market + A: −0.0002, CI [−0.0012, +0.0007];
  * market + B: −0.0006, CI [−0.0021, +0.0010].

  Engine B takes the larger weight (0.17–0.18 vs about 0). That suggests B carries information that is less redundant with the market, but the effect is not significant.
* **Averaging A and B does not help either:** ΔLL vs A −0.0008, CI [−0.0030, +0.0014].
* **Engine B under-predicts draws:** mean 0.240 vs 0.253 observed. Engine A gives 0.250 and the market 0.247.
* **No tuning protocol, no reproducible production record,** and no live validation.

## 5. Important risks
1. **Unreproducible claims.** The documentation cites numbers that are not in the production DB, and the 1X2 Engine B result cannot be regenerated with the current code.
2. **The weekly 0.6/0.4 and shrink parameters cannot change on evidence,** because nothing tunes them.
3. **CLV against the same bookmaker's closing price** can look positive while real value is negative. The pattern seen here (+1.4% CLV with −23.5% ROI over 470 bets) is a warning sign.
4. **Live probabilities, if API-Football is connected,** would be shown without ever having been validated.
5. **Survivorship bias.** The 2–3% of matches that are not predicted are excluded from all metrics.

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria (measurable) |
|---|---|---|---|---|---|---|
| ML-1 | Persist a reproducible validation record. Run `backtest` and `engine_b.validation` in production; store the per-match prediction rows and the git SHA; regenerate the doc tables from the stored row. | PARTIALLY IMPLEMENTED | P1 | S | Autopilot weekly job | Every number in MODEL_VALIDATION and AI_INSIGHTS_VALIDATION matches a stored `backtest_runs` / `eb_validation_runs` row with the same SHA. `eb_validation_runs` ≥ 1. |
| ML-2 | Tune Engine A hyperparameters (xi, ridge, w_dc, elo_k, per-league Elo home advantage, newcomer prior) on a tuning period before 2025-08, then score once on 2025-08 → 2026-11. | MISSING | P1 | M | ML-1 | Holdout 1X2 ΔLL ≤ −0.002 vs current, n ≥ 4,800, paired-bootstrap 95% CI entirely < 0. **Reject** if the CI includes 0; keep the current parameters. |
| ML-3 | Promotion-aware priors. Seed Dixon-Coles and Elo for promoted teams from the historical performance of promoted teams in that league, and re-seed Elo at season start rather than at the first match. In Engine B, normalise features from the previous league and drop the 6-match gate in favour of shrinkage. | PARTIALLY IMPLEMENTED (A only) | P1 | M | — | Coverage ≥ 99.5% of target matches. On the newcomer subset (first 10 matches of promoted teams), model − market ΔLL improves by ≥ 0.01. The overall ΔLL CI does not show a worsening (upper bound ≤ +0.001). **Reject** otherwise. |
| ML-4 | Market-anchored log-linear stacking `p ∝ M^a·A^b·B^c`, fitted on a rolling origin. If accepted, re-derive the A and B `market_shrink` weights from the fitted pool, and use the result as the "best estimate" for value calculations. | MISSING (B's 0.25 is not derived from data) | P1 | S | ML-1 | Rolling-origin out-of-sample ΔLL vs market < 0 with CI excluding 0, on ≥ 4,000 matches. Otherwise **reject**: set B's shrink to the fitted value (about 0.17) and record that the model adds no information over the market. |
| ML-5 | Measure CLV against the **de-vigged sharp closing price** (BFE/PS closing) and report it alongside the current same-book CLV. Make the Engine B validation use the live quality/confidence gates and a configurable market list. | MISSING | P1 | S | — | Both CLV figures are reported for ≥ 100 bets. Promotion to "evidence of edge" needs sharp-CLV CI > 0 **and** ROI CI excluding 0. Engine B validation strategy equals the live rules (unit test). |
| ML-6 | Engine B draw and dependence: fit rho on a wider grid and add a draw-inflation term or a bivariate-Poisson covariance; check the negative-binomial alternative for goals. | MISSING | P2 | S | ML-1 | Engine B 1X2 ΔLL ≤ −0.002 vs current (CI < 0) with no O/U 2.5 regression (ΔLL CI upper bound ≤ +0.001). Draw bias below 0.005. **Reject** otherwise. |
| ML-7 | Fit the ordered-logit thresholds per league (a draw-rate offset), keeping beta global. | MISSING | P3 | XS | ML-2 | Same criteria as ML-2, on the Elo component and the ensemble. |
| ML-8 | Isotonic or temperature calibration. | NOT RECOMMENDED now | P4 | XS | — | Tested: power calibration gives ΔLL −0.0002, CI includes 0. Revisit only if a rolling ECE exceeds 0.02. |
| ML-9 | Validate the live model: time-varying goal intensity, red-card time effects, score-state effects; score against minute-level outcomes. | BLOCKED BY EXTERNAL DEPENDENCY (API-Football key: owner approval, free tier) | P2 | M | Key, ≥ 300 live matches stored | In-play 1X2 log loss at minutes 15/30/45/60/75 beats the "pre-match probabilities held constant" baseline with CI < 0. Until then, label live probabilities "unvalidated". |
| ML-10 | Gradient boosting or other complex ML. | NOT RECOMMENDED | P4 | L | — | Only after ML-2 to ML-6, and only if a GLM with the same features is beaten by ΔLL ≤ −0.003 (CI < 0). |
| ML-11 | Add a leakage test for Engine A's `Engine.build`: appending a future match must not change predictions made before it. | MISSING | P2 | XS | — | The test passes in CI. |

**Experiment protocol for all of these:** identical matches; walk-forward with 14-day steps; paired bootstrap of per-match ΔLL with ≥ 4,000 resamples, preferably blocked by matchweek; one primary metric (1X2 or O/U log loss); thresholds fixed before the run. The baseline is always the current deployed model at commit `3a1ead6`.

### Best next 5 experiments, ranked
1. **ML-2** — Engine A tuning on an earlier period, scored on the holdout.
2. **ML-3** — Promotion and newcomer priors, which address both coverage and accuracy.
3. **ML-4** — Market-anchored stacking of A and B, which also sets the shrink weights from data.
4. **ML-6** — Engine B draw/dependence fix.
5. **ML-5** — Sharp-closing CLV and an Engine B validation that uses the live rules (an evaluation fix that every later betting decision depends on).

## 7. Top 3 recommendations
**1. ML-1 + ML-5: make the evidence reproducible and measure CLV correctly.** Every quality decision depends on these numbers, and today they cannot be traced. The documented validation numbers are not in production (`backtest_runs` has one older-format row; `eb_validation_runs` is empty). Engine B's documented 1X2 result cannot be reproduced with the current code. CLV is measured against the same soft bookmaker's closing price. Fixing this is cheap (S) and stops conclusions being drawn from noise or from a flattering benchmark.

**2. ML-2: tune Engine A on an earlier period.** No hyperparameter has ever been fitted. The stored scan already hints that w_dc = 0.4 is better (0.9942 vs 0.9947), and the market gap is concentrated in a few leagues (ENG2 +0.028, FRA1 +0.024, ESP1 +0.020). Elo home advantage is global and the draw thresholds are pooled. A disciplined tune on pre-2025 data, then scored once on the holdout, is the most likely low-risk gain. It is accepted only if the paired CI excludes 0.

**3. ML-3: promotion-aware priors in both engines.** About 2.7% of matches (133 of 4,978) are not scored by one engine or the other, and those are the ones involving promoted teams. On low-history matches Engine A trails the market by +0.024. The causes are in the code:
* Engine A's Elo re-seeding happens only after the team's first match;
* Engine A's newcomer prior disappears abruptly at 8 matches;
* Engine B carries old-league statistics into the new league without normalisation.

Fixing this improves coverage, which users see, and removes a selection bias from every reported metric.
