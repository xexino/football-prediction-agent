# Agent 3 (ML) — Cross-review of agent07_risk.md and agent02_data.md

## Agreements
* **RK-2 and RK-3 vs ML-5 and ML-1.** We found the same defects independently:
  * CLV is measured against the same bookmaker's closing price;
  * the Engine B validation hard-codes quality 80 and confidence 70 (`validation.py:130`);
  * `eb_validation_runs` is empty;
  * the documented figures were never stored in production.

  RK-2's definition is better than mine: EV against the de-vigged consensus close, minus the drift a random selection would show. I adopt it.
* **The 1X2 anomaly (RK-3).** Engine B 1X2 shows CLV +1.4% alongside ROI −23.5%. We both flagged it, and RK quantified it at about 2.9 standard errors.
* **RK-1, RK-9 and RK-10.** I endorse pre-registration, holdout discipline and flat stakes.
* **DS-6.** Per-league home advantage is consistent with my ML-7. Engine A's Elo also uses a single global value (`elo.py`, `home_adv=65`).
* **DS acceptance protocol.** DS uses the same rule as my ML experiments: Δ log loss ≤ −0.002 with a paired-bootstrap CI that excludes 0.

## Disagreements and corrections
1. **DS-5 has the wrong status.** It says MISSING and that "131 entrants start at Elo 1500". That is true for Engine B only (`features.py:135`). Engine A already handles newcomers:
   * unseen teams start at the 25th percentile of their league's peers;
   * promoted teams are re-seeded at the 20th percentile (`elo.py:24-37`);
   * Dixon-Coles adds a newcomer prior (`dixon_coles.py:147-149`).

   Correct status: **PARTIALLY IMPLEMENTED**. The remaining defects are that the Engine A re-seed fires only after the first match, and that the Engine B seed is fixed. DS-5 should be merged into ML-3.
2. **DS-1 is P0 but should be P1, and DS-3 is P0 but should be P1.** Nothing is critical for security or integrity in the sense the brief defines. Engine A never fits Dixon-Coles for UCL, because only competition codes ending in a digit are fitted (`engine.py:86`), so `predict` returns `None`. All validated domestic metrics are therefore untouched by DS-1, except rest days in Engine B.
   * The real exposure is 13 UCL predictions from Engine B, with mean data quality 43.
   * DS-3 involves 7 duplicate fixtures and 15 same-day double plays out of 56k results. The effect on ratings is local.
   * DS-2 (Andorra) can stay P0 because it is a data-integrity defect affecting a real ESP2 team.
   * I recommend P1 for DS-1 and DS-3, with an acceptance check that measures the impact: rerun the walk-forward before and after the fixes and report ΔLL.
3. **RK-5's BFE concern applies to bets, not to the market baseline.** I checked my paired run (`agent03_tmp/recs.json`):
   * BFE is the 1X2 reference on 4,601 of 4,844 matches, with market log loss 0.9814;
   * the worst single-match market loss is 4.07, so no glitched reference drives the baseline;
   * A − M gap by reference: +0.0128 with BFE, +0.0171 with Avg (n = 238).

   RK-5 stays valid for value and selection, at P1. It is not a reason to doubt the model-vs-market conclusion.
4. **RK says "Pinnacle disappears after Jan 2026".** I agree, and it affects my ML-4 stacking. PS was the reference on only 5 paired matches, so the stacking work should use Avg or a consensus reference, not PS.

## Changes to my own recommendations
* **ML-2.** The 2025-08 to 2026-11 window is "burned" (RK-9). DS also shows that the main leagues only start in 2023/24.
  * New plan: tune on 2024/25, with 2023/24 as burn-in. Keep 2025-08 to 2026-11 as a secondary check only.
  * The binding acceptance test is a **forward holdout** from the freeze date, at ≥ 1,500 matches.
  * Choosing w_dc = 0.4 from the stored scan would be in-sample, so it is not allowed.
* **ML-3** now includes DS-5 and DS-6 for Engine B. It depends on DS-2 and DS-3, so the baseline must be re-run after the identity fixes.
* **ML-4** depends on RK-5, using a consensus reference and storing `reference_book`.
* **ML-5** is superseded by RK-2 and RK-3, which I adopt as written. I keep only my addition: a unit test that the validation strategy equals the live rules.
* **New dependency for ML-1.** It should store the per-match rows, so that the DS-4 A/B harness and ML-2 to ML-6 share the same paired data.

Revised top 5: ML-1/RK-3 → RK-2 → ML-2 (forward holdout) → ML-3 (incorporating DS-5 and DS-6, after DS-2 and DS-3) → ML-4.
