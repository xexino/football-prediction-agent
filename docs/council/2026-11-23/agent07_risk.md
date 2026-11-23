# Agent 7 — Quantitative Risk and Virtual Betting Analyst

Reviewed commit `3a1ead6`; prod DB snapshot 2026-11-23 00:49 UTC (read-only). Everything here is simulation only. No real-money features are recommended.

## 1. Current situation
- **Live ledgers are empty.** `virtual_bets` = 0, `eb_bets` = 0. Each bankroll table holds a single `initial` €100 row. All 121 Engine A predictions are `NO_BET`. `eb_validation_runs` = 0.
- **Live rejections are mostly about missing prices.** Of 621 value assessments, 529 were rejected with "no bookable price". The others failed on quality, confidence or data-error filters. None qualified.
- **Historical evidence is thin.** There is one `backtest_runs` row (Engine A, 4,859 matches): 65 bets, ROI −22.0%, average CLV +1.77%, max drawdown 15.9u. That stored run has no `roi_95ci`. I bootstrapped its stored `cumulative_pnl` and got 95% CI −50.2% … +8.5%.
- **The brief's Engine A figure does not match the DB.** The brief says "−25%, CI −51…+2.5". The DB says −22.0% with no CI. The figure came from a scratch run that was not persisted.
- **Engine B figures exist only in a document.** `docs/AI_INSIGHTS_VALIDATION.md:42-46` reports:
  - 1X2: 470 bets, −23.5% [−36.7, −9.8]
  - O/U 2.5: 114 bets, −2.7% [−26.0, +23.4]

  These cannot be checked against the production DB, so they are UNVERIFIED there.

## 2. Evidence from the repository

### Rules
- **Engine A** (`config.py:27-56`): flat €1 stakes, ≤3 bets per match, ≤15 per day. Conservative probability `p_c = 0.10·model + 0.90·market`, EV ≥ +2%. Odds must be 1.50–5.00, margin ≤9%, model/market gap ≤15pp, odds age ≤96h.
- **Engine B** (`engine_b/betting.py:18-36`): shrink 0.25, edge ≥3%, odds 1.40–6.00, gap ≤20pp, markets limited to `("OU25",)`. 1X2 was disabled after the validation run.

### De-vig and reference books
- De-vig uses the power method (`models/markets.py:100-115`).
- Engine A's data-error filter uses proportional de-vig instead (`value.py:83`). The two are inconsistent.
- Reference book order is `BFE, PS, Pinnacle, Betfair, Avg` (`value.py:16`).
- **Pinnacle disappears from the data after January 2026.** Monthly `PS` pre-match rows: 162 in 2026-01, then 0 every month after. So from February 2026 onward, live and backtest references are Betfair Exchange (BFE) or Avg.
- **BFE prices can be corrupt.** Odds observation 347590: BFE pre-match draw = 1.10 against B365 3.75, overround +69%. That produced an assessment showing EV_c +171%. The filters rejected it (consistency check at `value.py:82-85`), but BFE is still ranked first.

### Odds timing
- `retrieved_at` is the time *we* downloaded the CSV (`ingest.py:201-202`), not the time the price was posted.
- All 94 upcoming pre-match rows share 2 distinct `retrieved_at` values (2026-11-22 21:04). Only 23 of the 143 fixtures in the next 7 days have odds.
- `odds_age = min(...)` across all books (`pipeline.py:117`). That is the age of the *freshest* book, not the book we bet at.
- The backtest hard-codes `odds_age_h=36` (`backtest.py:170-172`). It also hard-codes `stats_share=1.0` and `name_confidence=1.0`.
- Engine B validation hard-codes `quality=80, confidence=70` (`engine_b/validation.py:130`), which bypasses its quality and confidence gates entirely.

### CLV
- CLV is `price / same-book closing − 1`, Engine A at `betting.py:65-77, 104-109` and Engine B at `engine_b/betting.py:163-171`. The Engine B closing query has no `order_by`.
- CLV is computed only once, at settlement, and is never back-filled.
- AH CLV exists only if the closing line equals the bet line (`betting.py:75`). That is a selection bias.
- **Baseline drift is positive.** I compared B365 pre-match vs B365 closing over 10,063 matches (2025-08 to 2026-11):

  | Selection | Mean price/close − 1 | SD | Rows with identical prices |
  |---|---|---|---|
  | Over 2.5 | +0.21% | 6.0% | 19.8% |
  | Home | +0.10% | 9.0% | — |
  | Away | +0.36% | 10.9% | — |

  So a random selection already shows slightly positive "CLV". The 19.8% of identical prices suggests some closing values are stale copies of the pre-match price.

### Settlement
- `models/markets.py:119-151`: quarter-line AH is split in two halves, and pushes refund the stake.
- Matches that go to extra time settle on the 90-minute score via `regularTime` (`providers/football_data_org.py:190-195`; `ingest.py:234-243`).
- Conflicting sources keep the bet pending (`ingest.py:257-260`).
- Postponement rule (`betting.py:95-98`): the "finished" branch is evaluated **before** the 48-hour void check. A match replayed after 48 hours that the settle job never caught in between settles on the replay, which contradicts the rule stated at `markets.py:155-159`.
- Bets stuck pending because of a conflict have no timeout or alert.

### Ledger integrity
- Immutability triggers exist (`db.py:579-609`; all 30 are present in the prod DB).
- Engine A reconciliation (`integrity.py:44-67`): balance chain, stake count, settlement records, payout = credit, no bets after kickoff.
- Engine B (`integrity.py:77-87`): **only** the balance chain and stake count. There is no settlement-record check and no payout reconciliation.

### Tests
- `pytest -k "settle or ah or devig or void or postpon or bankroll or immut or kickoff"` gives 25 passed. Relevant tests include `test_settle_asian_handicap`, `test_ah_ev_consistent_with_settlement`, `test_postponed_bet_voided_after_48h`, `test_bet_after_kickoff_rejected_by_db` and `test_engine_b_ledger_settlement_independent`.

### Tuning history
- `docs/DECISIONS.md:93-104`: the first run (shrink 0.5) gave 2,046 bets at −8.0%. The rules were then changed, and the second run was evaluated on the **same period**.
- The doc says "Both backtest runs are stored in `backtest_runs`". The prod DB holds 1 row, so that statement is false.
- The blend weight w=0.10 was fitted on the first half of the data only, which is good practice. The strategy ROI, however, covers the full period, including that first half.

### Dashboard
- Live stats (`stats.py:28-35`, `api_b.py:146-150`) report ROI and average CLV with **no CI, no count of bets with CLV, and no sample-size warning**.
- `Overview.tsx:25` colours ROI green or red regardless of sample size. Only the backtest panels show `roi_95ci` (`Analytics.tsx:85`, `EngineB.tsx:50`).

## 3. What is working well
- The hard guardrails are in place:
  - flat staking that is never increased after losses (`betting.py:49`)
  - per-match and per-day caps
  - a DB trigger that blocks bets at or after kickoff
  - a trigger that blocks re-settlement
  - append-only odds and ledgers
  - a manifest guard against stale restores
- There is no Martingale, no forced selection, and NO BET is the default outcome.
- The bankrolls are genuinely separate (separate tables and triggers), and a test covers it.
- Shrinking toward the market by 0.90 is honest: the model's log loss (0.9947) is worse than the market's (0.9817), and the code admits this.
- Settlement logic is correct for 1X2, O/U 2.5 and whole and quarter AH lines. The extra-time and source-conflict handling is careful.
- Correlated 1X2+AH pairs on the same match are blocked (`value.py:170`).
- Disabling Engine B 1X2 is the right risk decision: its loss interval lies entirely below zero.

## 4. What is weak or missing
1. **The backtests do not test the live strategy.** Hard-coded quality, confidence and odds-age inputs mean the backtest selects a different set of bets than production would.
2. **CLV is a weak measure here.** It is the same-book raw price ratio, computed once, on the fd.co.uk Friday/Tuesday snapshot versus close. It does not use a de-vigged sharp consensus. The baseline drift is already positive. And it disagrees with the results: Engine B 1X2 shows +1.4% CLV alongside −23.5% ROI. With CLV +1.4% and a typical closing margin of about 5%, the expected ROI would be around −4%. The observed −23.5% is about 2.9 standard errors worse than that. **This anomaly is unexplained and should be investigated for a bug** (candidate causes: stale closing rows, the longshot mix, the BFE reference).
3. **Odds age is understated.** It is measured from our download, not from when the price was posted, and taken from the freshest book rather than the bet book. A simulated bet "placed" at 21:04 actually uses a price that may be a day old and may no longer exist.
4. **The reference book is fragile.** BFE is listed first even though it produces thin-market glitches. Pinnacle data ended in January 2026, and nothing records which reference book was used per assessment.
5. **The live sample is effectively zero.** At current coverage (23 of 143 fixtures with odds, 0 qualifying), the time needed to reach a meaningful sample is measured in seasons. Nothing on the dashboard says so.
6. **Engine B lacks Engine A's live filters.** It has no odds-age check, no cap on the bet book's margin, and no minimum team history.
7. **Engine B integrity checks are incomplete.** It has no payout or settlement reconciliation.
8. **The postponement order is wrong** (see section 2), and conflict-pending bets have no escalation.

## 5. Important risks

### Garden of forking paths
At least three configurations were judged on the same 2025-08 to 2026-11 window:
- the shrink-0.5 run
- the final rules
- the Engine B market subset

On top of that, Engine B O/U 2.5 was *kept* despite an interval spanning −26% to +23%. Any future "positive O/U ROI" on this same window would be in-sample.

### Misleading CLV
A positive average CLV is currently being shown while ROI is significantly negative. Users may read the CLV as evidence of skill.

### Stale-price optimism
The backtest assumes every bet is filled at the fd.co.uk snapshot price. The real price could have moved before the simulated placement time.

### Power
These are the bet counts needed for 80% power at α=0.05 (two-sided). They are computed from the per-bet profit standard deviation, odds·√(p(1−p)):

| True ROI | Bets at odds ≈ 1.9 | Bets at odds ≈ 2.8 |
|---|---|---|
| +5% | ~2,800 | ~5,600 |
| +3% | ~7,800 | ~15,700 |

With CLV measured in probability terms (SD ≈ 6% for O/U, ≈ 10% for 1X2), detecting +1.5% CLV needs about 125 O/U bets or about 350 1X2 bets. ROI cannot validate an edge at this project's scale. CLV is the only feasible primary metric, and only if it is measured properly.

### Dashboard over-interpretation
Green or red ROI tiles on a handful of bets are effectively noise presented as performance.

## 6. Recommendations

| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| RK-1 | Pre-register the evaluation protocol in `docs/EVALUATION_PROTOCOL.md`. Freeze the rule hash (ValueRules, RiskB, model version) with a start date. Name the primary metric: probability-space CLV against de-vigged consensus close. Make ROI secondary. Fix N_min (O/U ≥150 CLV-measured bets, 1X2 ≥400) and an analysis date. Forbid rule changes during the window, or restart the clock and log the change. | MISSING | P1 | S | none | Doc committed. Rule hash stored on every bet. Dashboard shows "evaluation window day X, n/N_min". |
| RK-2 | Redefine CLV as `EV_close = price × p_fair_close − 1`, where p_fair_close is a power-de-vigged consensus closing price (Avg or BFE closing, after sanity checks). Keep same-book CLV as secondary. Report how many bets had CLV measured, and the baseline drift of a random selection. Back-fill CLV when closing odds arrive later. Add `order_by` to the Engine B closing query. | PARTIALLY IMPLEMENTED | P1 | M | none | Each settled bet has both CLV fields or a reason it does not. Report shows mean CLV minus random-selection baseline, with a 95% CI. |
| RK-3 | Make the backtest replay the live gates: real quality and confidence scores, and per-book odds age capped at ≤96h. Remove the hard-coded 80/70/36 values. Persist **every** run, Engine B included, to the prod DB with params, `roi_95ci`, CLV and its coverage. Investigate the 1X2 CLV +1.4% vs ROI −23.5% anomaly. | PARTIALLY IMPLEMENTED | P1 | M | weekly job | `backtest_runs` and `eb_validation_runs` have ≥1 row each with `roi_95ci`. The anomaly is explained in the docs or a bug is fixed. |
| RK-4 | Odds-timing hygiene. Compute age from the **bet book's** observation and store `price_first_seen_at` per snapshot. Flag a simulated bet as "price possibly stale" when age is over 24h. In the backtest, also report results for bets whose price was still available at close or later (a fill-realism sensitivity check). | MISSING | P1 | S | none | `odds_age` is per bet book. The stale flag is shown in History. The sensitivity table appears in the backtest output. |
| RK-5 | Make the reference book robust. Use Avg (or the median of named books) first, and use BFE only when its overround is between −1% and +6% and it agrees with Avg within 4pp. Store `reference_book` on every assessment and bet. Apply the same rules in Engine B. | MISSING | P1 | S | none | No assessment uses a BFE price that fails the sanity check (test using obs 347590). `reference_book` column populated. |
| RK-6 | Dashboard honesty. Every ROI or CLV tile shows n, a 95% CI (Wilson or bootstrap) and the CLV coverage. Tiles stay grey with "insufficient sample (n < N_min)" until the threshold is met. Show a permanent banner: "No edge demonstrated; market log loss is better than the model". Show the NO_BET rate and the top reject reasons. | PARTIALLY IMPLEMENTED (backtest panels only) | P2 | S | RK-1 | No coloured ROI is shown below N_min. CI is shown on Overview, Analytics and Engine B. |
| RK-7 | Settlement fixes. Check `fx.kickoff_utc > bet.kickoff_utc + 48h` **before** the finished branch, so late replays are voided. Raise an alert or report item for bets pending more than 7 days after kickoff (conflicts). Add a test for a replay at +72h. | PARTIALLY IMPLEMENTED | P2 | XS | none | A new test passes. The health page lists stale-pending bets. |
| RK-8 | Engine B parity and integrity. Add odds-age ≤96h, a bet-book margin ≤9% and a minimum team history to `RiskB`. Add Engine B settlement-record and payout-reconciliation checks to `integrity.py`. | PARTIALLY IMPLEMENTED | P2 | S | none | `check_database` fails on an injected Engine B payout mismatch (new test). |
| RK-9 | Holdout discipline. Declare the 2025-08 to 2026-11 window "burned" (used for tuning). Report all future strategy evidence only on data after the freeze date, or on an untouched league or season. Apply a Bonferroni or Holm correction when several market or league segments are reported. | MISSING | P1 | XS | RK-1 | Reports label results "in-sample" or "holdout". Segment CIs are adjusted. |
| RK-10 | Kelly or any other variable staking. | NOT RECOMMENDED | — | — | — | Stay flat until RK-1 shows CLV > 0 with the lower 95% bound above 0 on holdout data. |
| RK-11 | Fix the docs: `DECISIONS.md:104` claims two stored backtest runs (the DB has 1). Also reconcile the brief's "−25%" with the stored −22.0%. | MISSING | P3 | XS | none | The docs and DB agree. |

## 7. Top 3 recommendations

1. **RK-1 + RK-9: pre-registered protocol and holdout.** The rules have already been changed after seeing results on the one window that exists. Without a frozen rule hash, a declared primary metric and an untouched evaluation period, any future positive number is uninterpretable. This costs almost nothing to put in place, and it is what separates a research lab from a tipster site. It also makes NO BET the explicit scientific default: the system makes no claim until N_min is reached.

2. **RK-2 + RK-3: CLV that measures something, from a backtest that matches production.** The power analysis shows that ROI needs thousands of bets to detect a realistic 2–5% edge. CLV is therefore the only feasible signal. But as currently measured it is positively biased by baseline drift, and it contradicts the significantly negative 1X2 results, which itself points to a possible data or settlement defect. The backtest also bypasses the live quality and confidence gates. Fixing both makes the one feasible metric trustworthy.

3. **RK-6: honest dashboard reporting.** With 0 live bets today and roughly 20 priced fixtures a week, the first months will show ROI on tiny samples. Coloured ROI tiles without CIs or N_min gating would mislead users even though the engine itself is conservative. Showing n, the CI, CLV coverage, the NO_BET rate and the "no edge demonstrated" banner keeps the simulation scientifically credible.
