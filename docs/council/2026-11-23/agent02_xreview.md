# Agent 2 — Cross-review of agent03_ml.md and agent04_analysis.md

## Agreements
- **ML-1 and ML-5 are prerequisites for my feature work.** My DS-4 duplicates ML-1, so I fold DS-4 into it. Sharp-closing CLV is supported by the data: Pinnacle closing odds exist for 35,813 fixtures and Betfair Exchange closing odds for 27,517.
- **ML-3 and MA-6 (promotion).** These match my measurement: the 131 newcomers average 1.08 points per game and a −0.40 goal difference in their first 10 matches.
- **MA-1, MA-2 and MA-9.** They are consistent with the data gaps I found. No odds exist for BTTS, corners or cards, so the confidence labels for those markets cannot be validated.
- **MA-11 and MA-13 are BLOCKED.** I agree. The `players`, `team_news` and live tables all have 0 rows.

## Disagreements and corrections
1. **My own error (DS-5).** I wrote that newcomers "start at Elo 1500". That is true only for Engine B (`engine_b/features.py:94,135`). Engine A already seeds a new team at the 25th percentile of its league, and re-seeds a promoted team at the 20th and a relegated team at the 80th (`models/elo.py:24-37`), as Agent 3 says. DS-5 becomes **PARTIALLY IMPLEMENTED (Engine A only)** and is merged into ML-3.
2. **The ordering of ML-2 is too early.** Tuning hyperparameters (xi, ridge, w_dc, home advantage) on data that still contains identity errors would fit those errors. The errors I counted:
   - a national team merged with a club (team 217, with 98 club and 102 international fixtures);
   - 3 clubs split in two by renames (Ham-Kam, Dinamo Bucuresti, Gornik Zabrze);
   - 7 duplicate fixtures that feed Elo twice;
   - the `athletic` alias resolving to Atleti.

   DS-2 and DS-3 (effort S) should come before ML-2. The effect on the 4,845-match holdout is probably small because most of these errors are outside the top leagues. ESP2 (the Andorra case) and the POL1, ROU1 and NOR1 renames are inside it.
3. **Neither report mentions the European-cup identity gap (DS-1).**
   - Engine B issues 13 UCL predictions with a mean data quality of 43. They come from 135 "Europe" teams that have no link to their domestic records.
   - Because those teams are separate, rest days for the big domestic clubs ignore European midweek games, which distorts Engine B's `rest_days` feature (`features.py:97`).
   - Agent 3's coverage and leakage analysis covers domestic leagues only, so its conclusions do not transfer to UCL.
   - Until DS-1 is fixed, UCL predictions should be labelled "isolated rating pool" or suppressed.
4. **Agent 4 understates the stats coverage.** It reports stats for "18 European leagues". The DB shows shots, shots on target, corners and fouls for **22** competitions (23,914 matches). 18 is the number of competitions with xG. MA-4 and MA-5 should target 22 leagues, with ENG5 limited to cards for 2023–26.
5. **Agent 4 understates the referee data.** MA-9 says "referee-free base rates". Referee names do exist in the English and Scottish fd.co.uk files (E0–E3, EC, SC0–SC3; E0 2025/26 has 380 of 380 rows filled). So DS-7 is an option for cards in those leagues, subject to an A/B test.
6. **Agent 4's standings example needs correcting.** It says "none for ARG1". In fact the only standings in the DB are one snapshot for 10 competitions, and there is no history. That blocks any walk-forward use of standings, not only ARG1.

## Status and priority corrections
- **ML-3:** correct as written. Add "Engine B Elo seeds at 1500" to its evidence.
- **MA-12** (IMPLEMENTED BUT NEEDS VERIFICATION): acceptable. The free football-data.org feed has no match minute (brief), so the live probabilities stay labelled DELAYED.
- **MA-6:** I would raise its effort from XS to S. The `recent` list only holds 20 matches, while the EWMA blends far more history, so the cross-league share needs its own counter.

## Changes to my recommendations
- DS-4 is merged into ML-1.
- DS-5 becomes PARTIALLY IMPLEMENTED and is merged into ML-3.
- DS-6 (per-league home advantage in Engine B's Elo) is merged into ML-2/ML-7 as the Engine B counterpart.
- DS-1, DS-2 and DS-3 remain P0 and must run before ML-2.
