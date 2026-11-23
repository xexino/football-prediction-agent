# Agent 12 — Independent Auditor / Devil's Advocate

Scope: all 11 specialist reports and 11 cross-reviews, checked against commit `3a1ead6` (read with `git show 3a1ead6:<path>`, because the local checkout has moved to `89211a4`, which only adds `publish-discussion.yml` and a docs file) and against `prod.db`, opened read-only.

## 1. Current situation
The council's diagnosis is largely sound and well evidenced. The product is safe by construction: NO BET by default, flat stakes and immutable predictions. It has no live track record yet: 0 bets, 0 settlements and 0 evaluations. Its own evidence says it beats naive but not the market. The weak points are the GitHub Actions persistence loop, a few integrity gaps, and analyst text that overstates confidence.

The combined output still suffers from three problems:
- **Inflated P0s.** 17 items were proposed as P0 (§4).
- **Duplication.** The same live-cron/quota/persistence fix appears under 9 IDs.
- **Over-reach.** There are proposals for Cloudflare workers, blended headlines, ClubElo benchmarks and growth targets before a single prediction has been settled.

## 2. Evidence: my own spot checks
| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | QA-1: settled bet payout/profit is mutable | **CONFIRMED, but narrower than stated** | `payout, profit, settled_at, closing_price, clv` are missing from `IMMUTABLE["virtual_bets"]` (`db.py:555-558`); `trg_bets_no_resettle` fires only `OF status` (`db.py:591-594`). `settlements` itself is fully immutable, but dashboard ROI reads the mutable copy (`stats.py:25`), and integrity never compares the two (`integrity.py:61-64`). |
| 2 | QA-2: `fil integrity` re-creates triggers before checking them | **CONFIRMED** | `cli.py:55-63` calls `init_db()`, which runs `CREATE TRIGGER IF NOT EXISTS` (`db.py:645-649`), for every command except `guard`/`restore`. The restore step calls `python -m fil integrity` (`autopilot.yml:72`). |
| 3 | QA-3: an empty dashboard is force-pushed after a failed restore | **CONFIRMED** | A failed download exits 1 (`autopilot.yml:62`) and Persist skips (`:104`). Export (`:125-127`, `if: always()`) then runs `init_db()` on a fresh, empty DB, and Publish runs `git push -f` (`:137`). No DB is lost, because Persist runs first. |
| 4 | DP-4: freshness is measured from retrieval time | **CONFIRMED, status MISSING** | `provider_updated_at=now` (`live.py:175`), and `label_for` uses it (`live.py:237-244`). The football-data.org live provider has `minute: False` (`live.py:64`), so LIVE cannot be produced today. |
| 5 | DP-3: Odds API errors are masked | **CONFIRMED** | `mark_error` is followed unconditionally by `mark_success` (`collect.py:121-125`). |
| 6 | DS-1/DS-2: team identity | **CONFIRMED** | 135 teams have `country='Europe'`. Team 217 "Andorra" (Spain) has ESP2 98, UNL 46, WCQ 28 and INTFR 28 fixtures. Engine A has **0** UCL/UEL/UECL predictions, because it fits only codes ending in a digit (`engine.py:86`). Engine B has 13 UCL predictions with mean data quality 43.1. Team 217 has **0** current predictions in either engine. |
| 7 | `eb_validation_runs`=0 means the validation is broken | **REFUTED as a defect** | The only weekly run (job_runs #2) ran at 2026-11-22 21:23. The `eb_validation` step was added later, in `22c7eaa` (2026-11-23 00:21). `validation.run()` persists `EBValidationRun` (`validation.py:168`). The first chance is today's Monday 06:25 cron. Status: IMPLEMENTED BUT NEEDS VERIFICATION. RK-3's hard-coded 80/70 values still apply. |
| 8 | No scheduled run ever fired | **SUPERSEDED** | Run 45097471610, `event=schedule`, was created at **01:57:48Z** and was in progress at 01:59. It is most likely the 00:40 slot, about 77 min late (the cron is inferred, not shown by the API). The outcome is UNKNOWN. A 77-minute delay is strong evidence that live cron timing cannot be trusted. |
| 9 | Pinnacle ends in Jan 2026; BFE glitch | **CONFIRMED** | PS pre-match per month: 293 / 366 / 162 (2025-11 to 2026-01), then none. PS closing shows the same pattern. Obs 347590: BFE draw 1.10 against B365 3.75 and Avg 3.69. BFE is ranked first in `REFERENCE_BOOKS` (`value.py:16`) but is non-bookable. |
| 10 | 21 of 141 next-7-day fixtures have odds | **CONFIRMED** | 21 distinct fixtures. |
| 11 | MA-1: inflated labels | **CONFIRMED** | 102 of 130 `eb_predictions` contain "high (". |
| 12 | `queue: max` exists | **CONFIRMED in official docs source** | `github/docs` `data/reusables/actions/actions-group-concurrency.md` defines `queue: single` (default) and `max` (up to 100 pending; not combinable with `cancel-in-progress: true`). Its feature flag `actions-nga` is enabled for `fpt: '*'` (github.com). Not tested on this repository. |
| 13 | Odds API burn of about 290 credits a day | **CONFIRMED (arithmetic)** | 16 sports, `markets=h2h,totals`, `regions=eu` (`others.py:114-148`). The call sits in `collect_fixtures`, which runs in the `fixtures` job (8 a day) and the `daily` job. Whether empty responses are free is UNKNOWN. |
| 14 | README describes the API-Football adapter as a stub | **CONFIRMED** | `README.md:77`: "Reserved; the adapter is not implemented yet". The live adapter exists (`live.py:108-184`); the pre-match adapter does not (`others.py:174-187`). |

Two further findings that no agent reported:
- `predictions.component_probs` is stored on all 121 predictions. An Elo-only internal baseline therefore already exists.
- 8,364 Avg/BFE **closing** rows exist for fixtures finished since 2026-08. A post-match market benchmark therefore needs no new provider.

## 3. What is working well (do not rebuild)
Keep as is: the fail-closed restore and shrink guard (Agent 9 verified them); the trigger-enforced immutable prediction and settlement tables (all 30 triggers present); the settlement logic (25 targeted tests pass); secret scoping (tested); the honest README; the free-first 37-league data stack; the Insight detail page; and the walk-forward framework, which Agent 3 reproduced exactly. Nobody should touch the model architecture, the data stack or the hosting model.

## 4. What is weak in the council's output
1. **P0 inflation.** The following were all proposed as P0: LV-1, LV-2, LV-3, LV-7, OP-2, OP-3, DS-1, DS-2, DS-3, DP-1, UX-1, UX-5, QA-1, QA-2, QA-3, PM-3 and OP-1. By the brief's definition, only the items that can corrupt or misrepresent the record *today* qualify.
2. **Latent risks presented as current.** LV-1, LV-6, DP-1 and DP-4 all depend on a key that does not exist.
3. **Self-contradictions between merged items:**
   - QA-1 freezes `closing_price`/`clv` once a bet is settled, while RK-2 wants CLV back-filled when closing odds arrive later.
   - QA-4 ("refuse when the manifest is missing") conflicts with the manual reset procedure in `OPERATIONS.md:63-65`.
4. **A wrong rationale.** Agent 1 argues that DS-8 (The Odds API) is P1 because the scorecard needs a market benchmark. That benchmark already exists post-match: fd.co.uk closing odds (§2, second further finding). Odds API spending is not needed for PM-2.
5. **Overstated cancellation risk.** A cancellation needs a run in progress *plus* two more queued in the same window. Runs take about 2 minutes (Agent 10's timings). The risk is real only when GitHub delays bunch runs together, which the 77-minute delay shows can happen. That makes it P1, not P0.

## 5. Important risks the council under-weighted
- **Fragile autonomy.** The first scheduled run arrived about 77 min late. There is no alert path (failure e-mails go to a `noreply` cron author), and QA-3 would publish a fresh-looking empty dashboard. An outage would therefore stay invisible to everyone.
- **Missed predictions are a permanent gap.** A prediction must exist before kickoff. Missed or cancelled 3-hourly runs create a survivorship gap in the track record that cannot be repaired later. This, not settlement delay, is the real cost of scheduling problems.
- **Data redistribution.** DP-10: `db-latest` republishes 347k fd.co.uk odds rows publicly under unknown terms.
- **Cost and quota.** The only real quota risk is adding `ODDS_API_KEY` or `API_FOOTBALL_KEY` before DP-1 is in place. Actions compute is free on this public repository; it would exceed the Free plan's 2,000 minutes a month only if the repository became private (Agent 10).

## 6. Recommendations: see §9 (consolidated) and §10 (not recommended)

## 7. Top 3
1. **QA-3 + QA-2 + QA-1: make every check an honest gate.** Never publish when restore failed, never let the integrity check heal itself, and lock settled ledger fields with a cross-check. This must land before the first bet settles. The total effort is S, and it protects the product's only real asset: a trustworthy record.
2. **OP-4 + OP-1: prove the schedule and make failure audible.** Open a GitHub issue on failure or when no run has succeeded in 8 h, have the owner re-save the cron line, and record schedule delay. A track record that silently stops is worthless, and today nobody would know.
3. **RK-1 + RK-9 + GR-1 (minimal): freeze the protocol and timestamp predictions externally.** Do this now, while n = 0, because it cannot be done retroactively. Use plain append-only commits; OpenTimestamps is optional.

## 8. Disagreement rulings
**R1. Live cron: switch off, or gate it (Agents 6 vs 10)? And LV-3/OP-2 at P0 or P1 (Agent 9)?**
Ruling: **gate it, don't kill it; P1, effort S.**
- Agent 6 is right that the cron has value: the football-data.org key is configured, and its delayed scores feed the `live` phase (`api_b.py:84`).
- Agent 9 is right about the priority. Every job is idempotent, and a wasted live run harms nothing except bandwidth and upload exposure.
- Gate on a covered kickoff in [now−150, now+5] min **before restore**, persist only when rows changed, and skip the artifact on live runs (OP-8 live half).
- Gating on API_FOOTBALL_KEY alone is wrong, because the football-data.org path would then never run.
- Fallback if the gate slips by more than 2 weeks: delete the four colliding :40 live slots (Agent 6, XS).

**R2. DS-1/DS-3: P0 or P1?** Ruling: **P1** (Agent 3 wins).
- Engine A never predicts UCL (verified 0 predictions; `engine.py:86`), so no validated metric is affected.
- The exposure is 13 Engine B UCL predictions at data quality 43.
- DS-2 (Andorra) is also P1: team 217 has 0 current predictions. It is cheap, so bundle it.
- Add a **P1 XS interim**: label Engine B UCL predictions "isolated rating pool". All three must land **before** ML-2/ML-3 tuning.

**R3. PM-4 blended number.** Ruling: **NOT RECOMMENDED now (P4).**
- Agent 3 measured no gain from averaging A and B (ΔLL −0.0008, CI includes 0), and no significant gain from stacking with the market.
- Deliver the user need through UX-4 instead: the market as anchor, with A and B shown as labelled deviations.
- Revisit only if ML-4 passes its pre-registered test.

**R4. LV-1 at P0 or P1; LV-7 at P0 or blocked.**
- **LV-1: P1, as a hard release gate before `API_FOOTBALL_KEY` is added.** Today no LIVE label can exist (`live.py:64`, `:241`).
- LV-2, the live phase held for 3 h, is **not** latent: football-data.org DELAYED snapshots will appear as soon as a covered match is polled. LV-2 is therefore **P1** and lands before LV-1.
- **LV-7's wider 00–03 UTC window: BLOCKED** (no minute feed, quota). Its minute-stagger half merges into OP-3.

**R5. DP-4 status; DP-1 priority.**
- **DP-4: MISSING** (`live.py:175`). P1, paired with LV-1 as the same release gate.
- **DP-1: P1, a hard gate that blocks DP-5.** No key exists, so there is no exposure today.
- Until DP-1 merges, OPERATIONS.md must say "do not add ODDS_API_KEY / API_FOOTBALL_KEY".
- DP-1 must persist its counter (`quota_info`) and must not reset the circuit breaker on 429. That couples it to DP-3.

**R6. BFE and ClubElo benchmarks.**
- **BFE is sound as a log-loss baseline.** Agent 3 found it was the reference on 4,601 of 4,844 matches, the worst match loss was 4.07, and the gap was similar to Avg's. It is **unsound as the CLV or bet reference** without RK-5's sanity filter (obs 347590). PS is dropped because it ends in Jan 2026.
- **Primary benchmark:** power-de-vigged Avg/consensus closing price, with BFE accepted only after the sanity check.
- **ClubElo: NOT RECOMMENDED.** It is blocked (DATA_SOURCES.md:51). It provides ratings, not 1X2 probabilities, so it would need a draw model that could be tuned. The free Elo-only baseline already stored in `component_probs` covers the same ground.

**R7. QA-1/QA-2 at P0.**
- **QA-2: P0 confirmed** (XS). An integrity check that repairs what it is meant to detect gives false confidence.
- **QA-1: P0 confirmed, re-scoped.** Freeze the bet columns once status ≠ pending. Allow `closing_price`/`clv` a single NULL→value transition (`WHEN OLD.clv IS NOT NULL`), which resolves the conflict with RK-2's back-fill. Add the integrity cross-check `virtual_bets.payout = settlements.payout` for both engines, since dashboard ROI reads the mutable copy. Making `model_versions.params` immutable is safe: rows are only inserted (`pipeline.py:29-33`). Deadline: before the first settlement.

**R8. QA-3 severity.** **P0 confirmed, XS.** The DB is not lost, but the published dashboard would look fresh and empty, hiding the outage on every following run until a human intervenes. Combined with the missing alerting, that is the worst failure mode found. Fix: `if: steps.restore.outcome == 'success'` on Export and Publish, plus export to a temp directory and push only if `health.json` exists.

**R9. `queue: max`.** **Exists (VERIFIED in the official github/docs source, enabled for github.com).** It has not been tested on this repository, and linters may not know it. OP-3 is **P1 XS**: add `queue: max` and stagger the minutes (live `7,27,47`; three-hourly `52`). Accept only after 14 days with 0 `cancelled` runs.

**R10. Other conflicts**
- **QA-4 vs the documented manual reset:** keep the reset as an explicit `workflow_dispatch` input (Agent 10). Merge QA-4 with OP-5.
- **UX-5: P1, not P0.** The data is already badged ODDS ERROR and no decision uses it. Ship it in the same PR as UX-1, which stays **P0 XS** for compliance and integrity (`styles.css:83`).
- **ML-2 order:** after DS-1, DS-2 and DS-3, and after RK-9. It is P2, not P1: the stored scan gains only 0.0005, and its binding forward holdout needs at least 1,500 post-freeze matches, which is months away.
- **DS-8: P3, BLOCKED.** It is not needed for the benchmark; it adds pre-match coverage only after DP-1.
- **QA-10's dead-man check runs on the same scheduler it watches** (Agent 10). It still has value for failed or stalled runs. Owner checks (OP-9) cover the "never fires" case.

## 9. Consolidated backlog (top 25, deduplicated)
| # | Merged IDs | Recommendation | Pri | Effort | Status | Category | Owner |
|---|---|---|---|---|---|---|---|
| 1 | QA-3 + OP-13 | Export and publish only after a successful restore; temp-dir export; push only if complete | P0 | XS | MISSING | bug fix | A9/A10 |
| 2 | QA-2 | `fil integrity` checks the raw file before `init_db`; test: drop a trigger → exit 1 | P0 | XS | MISSING | bug fix | A9 |
| 3 | QA-1 (+ RK-2 back-fill clause) | Freeze settled bet fields, eval_* and model params; one-time CLV fill; payout cross-check; trigger SQL check | P0 | S | PARTIAL | bug fix | A9 |
| 4 | UX-1 + UX-5 | Disclaimer and freshness visible on mobile; suppress EV on flagged odds | P0 (UX-5 P1) | XS | MISSING | dashboard | A8 |
| 5 | OP-1 + PM-3 + OP-4 + QA-10 + OP-9 | Verify schedules; issue-on-failure / no-success-in-8 h; owner re-saves the cron; record schedule delay | P0 | S | NEEDS VERIFICATION (first schedule fired 01:57) | reliability | A10 |
| 6 | QA-4 + OP-5 | DB first, manifest last, sha256 in the manifest, post-upload verify, explicit reset input | P1 | S | PARTIAL | reliability | A10 |
| 7 | LV-3 + OP-2 + OP-8(live) | Gate live runs on the kickoff window before restore; persist only on change; no artifact | P1 | S | MISSING | live | A6 |
| 8 | OP-3 + LV-7(stagger) | `queue: max` and staggered cron minutes | P1 | XS | MISSING | reliability | A10 |
| 9 | QA-13 + OP-14 | Scope `GH_TOKEN` to the persist and publish steps; pass inputs via `env:`; lock file | P1 | S | PARTIAL | reliability | A9 |
| 10 | RK-1 + RK-9 + GR-1 (minimal) | Frozen protocol and rule hash; burned window; append-only daily ledger commit (no force-push) | P1 | S | MISSING | data | A7/A11 |
| 11 | ML-1 + RK-3 + RK-11 + DS-4 | Verify today's weekly eb_validation row; replay live gates (remove 80/70/36); store SHA and per-match rows; docs match DB (−22.0%, 1 run) | P1 | M | NEEDS VERIFICATION | model | A3/A7 |
| 12 | RK-2 + RK-5 + ML-5 + QA-8 | CLV vs de-vigged consensus close minus random drift; BFE sanity filter; `reference_book`; Engine B `order_by` | P1 | M | PARTIAL | model | A7 |
| 13 | MA-1 + MA-2 + MA-3 + MA-6 + MA-9 | Analyst honesty: absolute-probability labels, confidence capped without validation, symmetric factors, ≥10% effects, cross-league flag, no hard-coded figures | P1 | M | PARTIAL | model | A4 |
| 14 | DS-1 + DS-2 + DS-3 (+ XS interim label) | Team-identity fixes and integrity checks; label UCL "isolated pool" now | P1 | M | MISSING | data | A2 |
| 15 | DP-1 + DP-3 + LV-6 + QA-16 | Persisted quota guard; live adapter through `Provider.get`; fix `mark_success` masking. Hard gate before any key | P1 | S | MISSING | reliability | A5 |
| 16 | LV-2 + LV-4 | Live phase expires 45 min after the last snapshot; per-match error isolation | P1 | S | MISSING | live | A6 |
| 17 | DP-10 | Record redistribution terms for fd.co.uk and football-data.org; gate the public DB release and GR-4 | P1 | XS | UNKNOWN | data | A5/owner |
| 18 | DP-2 + LV-10 + PM-8 + UX-12 | One truth on API-Football (live yes, pre-match no, 48–192 req/day); consistent provider status; "expected goals (model)" | P1 | XS | PARTIAL | dashboard | A5/A8 |
| 19 | PM-2 + UX-7 + RK-6 + MA-10 + UX-15 | Track Record page: A, B, closing market, naive and Elo-only, with n, CI and N_min gating; collapse €0 tiles; no "Compare" link to empty content | P1 | M | PARTIAL | dashboard | A1/A8 |
| 20 | LV-1 + DP-4 | Browser age relabelling and provider-time freshness. **Release gate for API_FOOTBALL_KEY** | P1 | S | MISSING | live | A6/A5 |
| 21 | UX-2 + UX-4 + UX-3 + PM-1 | Canonical match page with source chips; 4 task-based nav sections | P2 | M | PARTIAL | dashboard | A8 |
| 22 | OP-6 + QA-15 + OP-7 + OP-10 + QA-9 | Honest backup and settlement health; weekly restore drill; owner's monthly off-GitHub copy | P2 | S | MISSING | reliability | A10 |
| 23 | RK-7 + RK-8 + QA-6 + QA-7 | Postponement order; Engine B integrity parity; merge-duplicates FK guard; post-settlement correction flag | P2 | S | PARTIAL | bug fix | A7/A9 |
| 24 | UX-10 + PM-9 + UX-6 + UX-8 | Drop `no-store` polling, lazy routes, smaller payloads, mobile tables, accessibility basics | P2 | M | MISSING | dashboard | A8 |
| 25 | ML-2 + ML-3 + DS-5 + DS-6 + ML-7 | Tuning and promotion priors on a pre-2025 tuning period; accept only on the forward holdout. After #14 and #10 | P2 | M | MISSING | model | A3 |

Lower priority:
- P2: GR-3 (owner); QA-5 (self-heals after 90 min); RK-4; DP-5/DP-6 (BLOCKED by owner and #15).
- P3: MA-4/5/8 (after #21); DS-7; ML-4 (only "fit B's shrink"); ML-6; QA-11 (at the first schema change); QA-12; DS-8 (BLOCKED).
- P4, BLOCKED: LV-5, LV-8, ML-9, UX-14, MA-11, MA-13.

## 10. Not recommended
| Item | Reason |
|---|---|
| PM-4 blended headline | No measured gain from A+B or market stacking (Agent 3); it would hide disagreement. Use UX-4 |
| ClubElo comparator (GR-2 part) | Blocked host; ratings need a tunable draw model; `component_probs` Elo baseline is free |
| Live stages 2–5 (Cloudflare Workers/KV, VM; OP-12) | Second runtime and secrets location before DP-5 shows that a free minute feed exists; limits not verified |
| LV-9 `live.json` / `live.db` split | Redundant once LV-3 is in place; adds a merge path |
| Turning off the live cron entirely (OP-2a) | Removes the working football-data.org delayed feed; gating achieves the same savings |
| LV-7 00–03 UTC window (now) | No minute feed; adds runs against a future quota |
| DS-8 Odds API "for the benchmark" | Closing odds already exist post-match (8,364 Avg/BFE closing rows since August) |
| ML-8 calibration, ML-10 GBM, MA-14 LLM rephrasing | Measured null effect, or complexity for show |
| GR-5 "disagreement picks", PM-5 "odds moves" feed | Forking paths and gambling-promotion framing; revisit only after RK-1 and GR-7 |
| GR-9 star targets, PM-7 calibration game | Vanity metrics or a distraction while n = 0 |
| OpenTimestamps and external dead-man SaaS as requirements | Optional; free tiers not verified; plain commits plus GitHub issues suffice |
| DP-8 paid feeds, RK-10 Kelly, DS-12 weather/manager | Owner approval needed, no evidence of value, or no data source |

### First 5 tasks
1. **QA-3 (+OP-13)**: guard Export and Publish on `steps.restore.outcome`. *Why first:* it is XS, and it is the only defect that hides an outage from everyone. The first scheduled run is happening now.
2. **QA-2 + QA-1**: an honest integrity check and frozen settled fields, with the one-time CLV fill. *Why first:* both must exist before the first bet settles, and a settled record cannot be re-made trustworthy afterwards.
3. **OP-1 + OP-4 alerting**: watch today's scheduled runs (01:57 and Monday 06:25), open a GitHub issue on failure or a gap of more than 8 h, and have the owner re-save the cron. *Why first:* autonomy is unproven (the first run was about 77 min late), and nobody receives failure mail.
4. **UX-1 + UX-5 + DS-1 interim label**: show the mobile disclaimer, suppress EV on flagged odds, and label UCL predictions "isolated pool". *Why first:* three XS changes that stop misleading output today.
5. **RK-1 + RK-9 + minimal GR-1**: commit the protocol and rule hash, and start an append-only daily ledger. *Why first:* the track-record clock is starting now, and pre-kickoff proof cannot be added retroactively. Everything in #10–#13 is measured against this freeze.
