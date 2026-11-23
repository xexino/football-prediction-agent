# Agent 11 — Cross-review of Agent 1 (Product) and Agent 7 (Risk)

## Agreements
* **PM-1 and PM-2** (reposition the product around a public Track Record) are the same thesis as **GR-2**. I endorse them as the core differentiator. **PM-10** and **GR-8** agree: do not chase live, props or LLM features.
* **PM-3 at P0** is correct. A track record is only worth something if it is continuous, and no scheduled run has been observed yet (brief).
* **RK-1 and RK-9** (pre-registered protocol, "burned" in-sample window) are the scientific half of my **GR-1**. GR-1 timestamps the *predictions*. RK-1 freezes the *rules and metrics*. Both are needed.
* **RK-6** (n, CI, grey tiles until the minimum sample size is reached) is required for any public scorecard or social post, and it supports my risk that small-sample numbers will mislead.
* **RK-10**: no Kelly staking. Agreed.

## Disagreements and corrections (with evidence)
1. **Agent 1's odds coverage is overstated.** Agent 1 says "74 of 141 upcoming-7-day fixtures have any odds" (≈52%). My read-only query found 141 fixtures kicking off between 2026-11-23 and 2026-11-30 01:00, and only **21 distinct fixtures** with `odds_observations` (all `pre_match`). That is 25 fixtures if the window starts 2026-11-22 22:00. Agent 7's 23 of 143 agrees with this. Agent 1's metric baseline ("with odds reference ≥70%, now 52%") should be about **15%**. Agent 1's target is therefore far harder to reach and depends on new sources (PM-11, PRV agents).
2. **Neither report fixes the external verifiability gap.**
   * PM-2 and RK-1 store evidence in the DB, which is `--clobber`-uploaded. The gh-pages history is force-pushed and rebuilt on every run (`autopilot.yml:113-137`), and only 14 backups are kept.
   * RK-1's acceptance criterion "rule hash stored on every bet" proves nothing to an outsider.
   * **Proposed change:** RK-1 and PM-2 acceptance should also require that the rule hash and prediction rows are published in an append-only, non-force-pushed commit before kickoff (GR-1).
   * I would raise GR-1 to the same tier as RK-1 (P1). It is the dependency that makes PM-2's "immutable, timestamped" claim true.
3. **PM-2's acceptance criterion needs RK-9 labelling.** "n ≥ 200 evaluated within 3 weeks" is feasible: about 120–130 predictions per engine per week. But the scorecard must separate live holdout results from backtest results on the burned window. Otherwise it repeats the forking-paths problem that RK-9 describes.
4. **PM-5 (RSS briefing) and PM-7 (calibration game) need GR-7 content rules.** A daily "odds moves" feed is the item most likely to be read as gambling promotion under ASA/CAP-style rules. It should show probabilities, not prices or bookmaker names. PM-7 is fine as P3 provided there are no odds entry and no prizes, which Agent 1 already specifies.
5. **Minor priority point:** RK-11 (docs say 2 backtest runs, DB holds 1) should be P2, not P3. A public "radical transparency" brand cannot carry docs that contradict the DB.

## Changes to my own recommendations
* **GR-2:** replace "CLV" with **RK-2's** definition: de-vigged consensus close, with the random-selection baseline drift subtracted (+0.21% O/U, +0.10–0.36% 1X2). Gate every scorecard tile by **RK-1's** N_min, and label results in-sample or holdout per **RK-9**. Headline the 1X2 log loss vs market, because ROI is underpowered (RK power table).
* **GR-5** (engine-disagreement picks): the post-hoc score uses Holm correction and is labelled exploratory. It is never framed as a betting signal.
* **GR-4** (full ledger download): add `reference_book` and the rule hash columns once **RK-5** and **RK-1** land.
* **GR-1:** acceptance now includes the daily rule-hash file from RK-1.
* **GR-9** growth targets are unchanged, but social posting waits until GR-7 exists and PM-3 shows at least 3 consecutive successful scheduled runs.
