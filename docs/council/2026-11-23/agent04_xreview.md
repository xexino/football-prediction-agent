# Agent 4 — Cross-review of Agent 1 (Product) and Agent 6 (Live)

## Agreements
- **PM-1 and PM-2.** I agree with the honest-lab positioning and a public track record. My MA-10 (post-match review) is the per-match view of PM-2, so the two should share one data path through `eb_evaluations`, which currently has 0 rows.
- **PM-8.** I agree with renaming the model output from "xG" to "expected goals (model)" (`Insights.tsx:51`). This matters more than PM-8 suggests: we also hold *real* xG for 2,033 matches (`match_stats.home_xg`). MA-8 will display that real xG, so the two figures must be clearly distinguished.
- **PM-10.** I agree there should be no LLM rephrasing yet; this matches MA-14.
- **LV-2, LV-5 and LV-8.** I agree. My MA-11 (momentum) depends on LV-5's event reconciliation. Momentum built from unreconciled events, such as a goal later cancelled by VAR, would be wrong.
- **LV-12.** I agree: nothing on Pages should be called "live".

## Disagreements (with evidence)
1. **Agent 1 credits Engine B's explanations, including "what could make it wrong", as working well (§3).** I only partly agree. In prod, 30 of the 119 reports that list any risk give an effect under 10% as the "main uncertainty". 102 of 130 reports say "high confidence", and 16 call a favourite below 50% "clear" (DB queries in agent04 §2). The sections are there, but their content often misleads.
2. **PM-4, a single "Lab view" headline probability.** I agree with the idea, but it must not ship before MA-1. Showing one blended number next to today's "high (75/100)" label would increase the overconfidence. I would add a dependency on MA-1 to PM-4.
3. **PM-2 acceptance criteria.** These should also score the *confidence label*: do "high" predictions actually do better than "moderate" ones (log loss per label bucket)? Without that check, the label can stay uncalibrated indefinitely.
4. **LV-1 is rated P0, but the risk is latent today.** With football-data.org the minute is never supplied (`live.py:66`, `minute: False`), so a LIVE label is impossible (`live.py:242`). Only DELAYED or STALE can appear, and `eb_live_snapshots` has 0 rows. LV-1 becomes P0 *at the moment* `API_FOOTBALL_KEY` is added. Until then I rate it P1, and it should be a precondition in PM-11's dependencies.
5. **PM-11 (P2) versus my MA-13 (P4).** Agent 1 is right that lineups and injuries raise the data-quality ceiling: `team_news` scores 0 in every quality breakdown. I am splitting MA-13 accordingly.

## Wrong statuses or priorities
- My **MA-12** was "IMPLEMENTED BUT NEEDS VERIFICATION". Agent 6 shows live probabilities need a minute from the provider (`live.py:299`), and the free feed has none. The correct status is PARTIALLY IMPLEMENTED: delayed scores only, with live probabilities BLOCKED BY EXTERNAL DEPENDENCY (API_FOOTBALL_KEY).
- **LV-8 (P2) and MA-11 (P4)** are consistent with each other, since both are gated on a feed that supplies the minute.
- **PM-5 (P2).** The "what changed" briefing should reuse MA-3's tension headlines, which flag large Engine A/B or market disagreements, so that the "we disagree with the market" items come from one generator.

## Changes to my recommendations
| ID | Change |
|---|---|
| MA-1 | Add: it must land before PM-4. Add a per-label calibration check to PM-2 |
| MA-8 | Add: the label distinguishes "expected goals (model)" from "xG (data, 2026/27)", in line with PM-8 |
| MA-10 | Merged into PM-2 as the per-match review panel; priority stays P2 |
| MA-12 | Status changes to PARTIALLY IMPLEMENTED / BLOCKED (live probabilities); depends on LV-1 and LV-2; P2 |
| MA-13 | Split. **MA-13a**, lineups and injuries: BLOCKED (API-Football), P2, same as PM-11. **MA-13b**, player ratings and player xG: BLOCKED, P4 |
| MA-11 | Add dependency LV-5 (event reconciliation) on top of the key |
