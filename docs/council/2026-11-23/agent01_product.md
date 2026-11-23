# Agent 1 — Chief Product Officer / Product Manager

Reviewed commit `3a1ead6`, prod DB snapshot (2026-11-23 00:49 UTC), live JSON fetched 2026-11-23 from GitHub Pages.

## 1. Current situation
Football Intelligence Lab (FIL) is a technically strong but **empty-of-evidence** product. It produces calibrated-looking 1X2 / totals / props probabilities for ~130 fixtures a week across 38+ leagues, explains them, and runs two virtual €100 bankrolls. But as of the snapshot it has **no live track record at all**: 121 Engine A predictions (all NO BET), 130 Engine B predictions, 0 bets, 0 settlements, 0 production validation runs, and every prediction is still on a `scheduled` fixture. Its own walk-forward evidence says the models **beat a naive baseline but not the market**, and the value-betting strategy loses money. The product is therefore positioned as a betting-value tool while its evidence supports something else: an honest, auditable football-probability and match-briefing lab.

## 2. Evidence from the repository
| Fact | Evidence |
|---|---|
| 12 nav items: 8 "lab" pages + 4 AI pages; 3 of 12 are ops (Sources, System, Coverage) | `frontend/src/main.tsx:21-26` |
| No team page, no follow/favourites, no persistence of user choice, no notifications | `grep localStorage/follow/favourite frontend/src` → no hits; backlog M-1 TODO (`docs/PRODUCT_BACKLOG.md:86`) |
| Insights page already has tabs (upcoming/live/results), region/competition/date filters, free-text search | `frontend/src/pages/ai/Insights.tsx:7-40` |
| 121 predictions, all `NO_BET`; 0 of 621 value assessments qualify | DB: `select decision,count(*) from predictions` → `NO_BET 121`; `select sum(qualifies) from value_assessments` → 0 |
| Dominant reject reason: "no bookable price from a named bookmaker" (529/621); rest are quality <70, history <20, confidence <55 | DB query on `value_assessments.reject_reasons`; rule at `backend/fil/value.py:64-66` |
| Only 21 of 141 fixtures kicking off in the 7 days after the snapshot have any odds (16 with a bookable B365/PS/BW price). *Corrected in cross-review; an earlier figure of 74 counted past-dated fixtures still marked scheduled* | DB query on `odds_observations` ⨝ `fixtures`, kickoff 2026-11-23 00:49 → +7 d |
| Prod backtest: ensemble log loss 0.9947 vs market 0.9817 vs baseline 1.0763 (n=4,859, 11 leagues) — consistent with brief claim | DB `backtest_runs` id 1 |
| Engine B bankroll restricted to OU 2.5 only (1X2 disabled by evidence) | live `/data/engine_b/performance.json` → `risk.markets: ["OU25"]`; `validation: null` |
| `eb_validation_runs` = 0 rows in production | DB query |
| Job runs: 10 total (2 daily errors); all Autopilot runs are `workflow_dispatch`, none `schedule` | DB `job_runs`; `gh run list -w autopilot.yml` (6 runs, all dispatch) |
| Prediction self-evaluation exists (Brier/log loss per prediction, live calibration chart) | `backend/fil/pipeline.py:248-257`, `frontend/src/pages/Analytics.tsx:50,58` |
| Coverage: 146 fixtures in insights feed — 93 FULL, 28 PARTIAL, 18 FIXTURES ONLY, 7 COVERAGE ONLY | live `/data/insights.json` |
| Inconsistent provider status: coverage matrix says football_data_org `configured: false`, health says `configured: true` | live `/data/coverage_matrix.json` `live_providers[1]` vs `/data/health_detail.json` `providers.football_data_org` |
| README says API-Football adapter "not implemented yet" while docs describe it as implemented/mock-tested | `README.md:77` vs `docs/PRODUCT_BACKLOG.md:102` (LV-3 "mock tests"), `backend/fil/providers/others.py` |
| Upcoming payload is 1.07 MB JSON, insights 157 KB (mobile cost) | curl size of `/data/upcoming.json`, `/data/insights.json` |
| Engine B card labels model expected goals as "xG" | `frontend/src/pages/ai/Insights.tsx:51` |

## 3. What is working well
* **Integrity as a product feature.** Immutable predictions (SQLite triggers), stored inputs/odds IDs, NO BET reasons, stale-snapshot banner (`main.tsx:30-43`), honest README status table. Very few public prediction sites make this auditable.
* **Honest negative results.** The product publishes "does not beat the market" and disabled a losing market (Engine B 1X2). This is rare and is the brand.
* **Breadth of markets and explanations.** Engine B covers goals, BTTS, totals, correct score, corners, cards, shots with "what could make it wrong" and "missing information" sections (`docs/AI_INSIGHTS_ENGINE.md`).
* **Zero running cost.** GitHub Actions + Pages + free data; no paid dependency.

## 4. What is weak or missing
1. **No visible track record.** Users cannot yet see "we said 62%, here is how 62% calls performed" because nothing has settled. The core proof asset of the product is at n=0.
2. **The headline loop (value bet) is silent by construction.** 0/621 qualify; most fail on missing bookable prices, and the strategy has negative backtest ROI (Engine A 65 bets −25%). An 8-page "bet slip / bankroll / history" funnel shows empty states to every visitor.
3. **Ops pages dominate navigation.** Sources, System Health, Coverage are maintainer views presented as user features.
4. **No reason to return.** No team/league follow, no "what changed since yesterday" (odds move, probability revision), no digest/notification, no personal prediction game.
5. **Two engines, no single answer.** A user sees Engine A, Engine B and sometimes market prices with no guidance on which to trust. The comparison page exists but there is no blended "Lab view".
6. **Trust papercuts.** Contradicting provider status, README/doc mismatch, "xG" meaning model expectation.

## 5. Important risks
* **Credibility risk:** launching user-facing claims before any live evidence exists. Mitigation: show sample size everywhere.
* **Positioning drift toward tipster/betting:** the evidence says the edge is not there; leaning into "value bets" invites real-money use and contradicts the integrity brand.
* **Autonomy unproven:** scheduled runs not observed (`gh run list`), and GitHub disables schedules after 60 days of repo inactivity (`docs/PRODUCT_AUDIT.md:101`). A product whose value is a *continuous* record dies silently if runs stop.
* **Data ceiling:** odds source updates ~2×/week (`health_detail.json` odds detail); no lineups/injuries; scope creep into live/Africa depends on keys (owner approval).

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria (measurable) |
|---|---|---|---|---|---|---|
| PM-1 | Reposition: "honest football probability lab" — calibrated probabilities + public scorecard vs market and baseline; betting sim becomes a secondary "Strategy Lab" | MISSING | P1 | S | none | README hero + Overview lead with scorecard; nav ≤7 user items; ops pages under one "Lab internals" group |
| PM-2 | Public **Track Record** page: rolling log loss/Brier for A, B, market, naive on settled live predictions, reliability chart, n and CI, by league; every prediction linkable | PARTIALLY IMPLEMENTED (per-prediction eval + live calibration exist) | P1 | M | first settled fixtures; A-7 scheduled runs | page shows n≥200 evaluated predictions within 3 weeks; numbers reproducible from DB query; sample size shown on every metric |
| PM-3 | Make autonomy observable and loud (A-7 + M-1): GitHub issue opened on 2 consecutive FAILED/STALE health; keep-alive against 60-day schedule disable | PARTIALLY IMPLEMENTED | P0 | S | Actions | ≥3 consecutive scheduled runs succeed; ≥95% of expected 3-hourly runs succeed over 30 days; alert fires in a test |
| PM-4 | Single "Lab view" per match: one headline probability (documented rule: e.g. market-anchored blend, else best-validated engine), with A/B/market as drill-down | MISSING | P1 | M | validation evidence (Agent on models) | blend rule documented; blend log loss ≤ best single engine out of sample before shipping |
| PM-5 | "What changed" daily briefing: probability revisions, odds moves, newly-eligible fixtures, yesterday's results vs our calls; static `briefing.json` + page + optional RSS | MISSING | P2 | M | PM-2 | generated daily by autopilot; includes ≥1 "we were wrong" item when applicable; RSS validates |
| PM-6 | Follow teams/leagues (localStorage, no accounts) with a personal "My fixtures" feed | MISSING | P2 | S | none | follow persists across reloads; My fixtures renders <1 s on mobile |
| PM-7 | Calibration game (virtual, no money): user enters own 1X2 probabilities; scored by Brier vs Lab and market, stored locally/exportable | MISSING | P3 | M | PM-2 | user score computed for settled matches; no stakes, no odds-entry |
| PM-8 | Fix trust papercuts: provider-status contradiction, README API-Football row, rename "xG" to "expected goals (model)", sample-size labels | MISSING | P2 | XS | none | coverage matrix and health agree; README matches `providers/others.py`; e2e smoke passes |
| PM-9 | Slim payloads: paginate/split `upcoming.json` (1.07 MB) per day/league | MISSING | P3 | S | export-static | largest JSON on first load <300 KB |
| PM-10 | Do **not** prioritise: player props, goal timing, possession, LLM rephrasing, more value-bet markets, persistent live poller | NOT RECOMMENDED (for 0–6 months) | P4 | — | keys / hosting | revisit only after PM-2 shows ≥1,000 evaluated predictions |
| PM-11 | API-Football key for lineups/injuries (free 100 req/day) to raise data-quality ceiling | BLOCKED BY EXTERNAL DEPENDENCY | P2 | S (code exists) | owner adds key | team-news quality component >0 for ≥50% of top-5-league fixtures |

**Roadmap.** *3 months:* PM-3, PM-8, PM-1, PM-2 live with ≥1,500 evaluated predictions; PM-5 briefing. *6 months:* PM-4 Lab view, PM-6 follow, Strategy Lab (backtests of rule sets, CLV) replacing Bet Slip/History as front-door; PM-11 if key approved. *12 months:* a public, multi-season, reproducible football-forecast benchmark (FIL vs market vs baselines per league), the calibration game, and an open data/API export of immutable predictions so others can audit or compare.

**Metrics to track (targets).**
* Integrity: scheduled-run success ≥95%/30 days; dashboard freshness <4 h on ≥95% of checks; 0 integrity-check failures.
* Evidence: evaluated live predictions ≥1,500 by month 3, ≥6,000 by month 12; live 1X2 log loss within 0.015 of market and ≥0.06 better than naive (current backtest gap 0.013 and 0.082); live ECE ≤0.03.
* Coverage: share of 7-day fixtures with a published Lab probability ≥90% (now 130/146 ≈ 89%); with odds reference ≥70% (now 21/141 ≈ 15%).
* Engagement (needs privacy-friendly counter, e.g. GitHub Pages traffic insights — UNKNOWN today, no analytics present): weekly returning visitors, briefing/RSS subscribers, follows per user; target D7 return ≥25% of first-week visitors.
* Strategy Lab: CLV reported for 100% of virtual bets; no strategy promoted unless bootstrap ROI CI lower bound >0.

## 7. Top 3 recommendations
1. **PM-2 Track Record (with PM-1 repositioning).** FIL's only defensible differentiator against match-prediction sites is that every forecast is immutable, timestamped and scored in public against the market and a naive baseline. The code already stores per-prediction Brier/log loss and draws live calibration, but there is no front-door page and no settled data. Making the scorecard the homepage turns an empty bet slip into the product's strongest asset and matches what the evidence actually supports (good probabilities, no betting edge).
2. **PM-3 Observable autonomy.** The value of a track record is its continuity. No scheduled run has been observed, 2 of 8 daily runs errored, and schedules auto-disable after 60 idle days. A missed week silently corrupts the record's credibility. Alerting plus a run-success SLO is cheap (S) and protects everything else.
3. **PM-5 Daily "what changed" briefing (plus PM-6 follow).** Return visits come from change, not static tables: revised probabilities, odds moves, newly eligible fixtures, and a candid "yesterday we were wrong about X". It reuses existing data, needs no keys or accounts, and gives users a reason to come back every matchday, which a prediction website listing tips does not.
