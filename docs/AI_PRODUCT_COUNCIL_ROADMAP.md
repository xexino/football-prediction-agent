# AI Product Council — roadmap, backlog and recommendation register

Method and status definitions: [`AI_PRODUCT_COUNCIL.md`](AI_PRODUCT_COUNCIL.md). Each review appends a dated section here. History is never rewritten.
A recommendation becomes **APPROVED** only after the owner agrees in the council discussion; only then is one GitHub issue opened per ID.

---

## Review 2026-11-23 (commit `3a1ead6`)

* Full report: [`council/2026-11-23-review.md`](council/2026-11-23-review.md).
* Evidence: [`council/2026-11-23/`](council/2026-11-23/), 12 agent reports plus 11 cross-reviews.
* Source IDs (QA-1, LV-3 …) refer to those reports. Effort scale: XS < ½ day · S ≤ 2 days · M ≤ 1 week · L ≤ 3 weeks · XL > 3 weeks.

### 30 / 60 / 90 days
| Window | Theme | Items | Exit criteria |
|---|---|---|---|
| 0–30 | Trustworthy and audible | F-01…F-05, R-01, R-03, D-01, D-03, U-01, L-01, L-02, D-02a | ≥ 20 consecutive scheduled runs with no unalerted failure; 0 cancelled 3-hourly runs over 14 days; first settlements frozen; ≥ 25 ledger commits; Monday `eb_validation_runs` row present |
| 31–60 | Measured | R-02, R-04, R-05, M-01, M-02, M-03, D-02, U-02, D-04 | backtest replays the live gates and is stored with its git SHA; CLV definition published; "high confidence" on ≤ 15% of reports; 0 identity duplicates; Track Record shows n and CI |
| 61–90 | Proven and usable | U-03, U-04, R-06, M-04, L-03, L-04 (if approved), U-05 | ≥ 1,500 evaluated live predictions; scheduled-run success ≥ 95% over 30 days; no 390 px overflow; first monthly re-review |

### First five tasks
0. **F-08.** XS. CI is red on `main` because of a date-dependent test; fix it before any other PR so that CI means something again.
1. **F-01.** XS. It is the only defect that hides an outage from everyone.
2. **F-02 + F-03.** Must land before the first bet settles; a settled record cannot be repaired afterwards.
3. **R-01.** Autonomy is unproven: the first scheduled run started about 77 minutes late, and nobody receives failure mail.
4. **F-04 + D-02a.** XS changes that stop misleading output today, including the disclaimer.
5. **D-01.** A pre-kickoff proof cannot be added retroactively, and every later metric is measured against this freeze.

---

### Category 1 — Immediate bug fixes

| ID | Title | Problem | Proposed solution | Expected benefit | Pri | Effort | Deps | Data req. | Technical req. | Risks | Acceptance criteria | Validation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F-01 | Never publish after a failed restore (QA-3, OP-13) | A failed restore leaves an empty DB. Export (`autopilot.yml:125-127`, `if: always()`) still runs and `git push -f` publishes an empty dashboard | Guard Export and Publish with `steps.restore.outcome == 'success'`; export to a temp dir; push only if `health.json` exists | Outages stay visible; the last good site is kept | P0 | XS | — | none | workflow change | none significant | A simulated restore failure leaves the gh-pages HEAD unchanged | CI job with a forced restore failure; Actions log | A9 / A10 |
| F-02 | Integrity check must not heal itself (QA-2) | `cli.py:55-63` runs `init_db()` before `integrity`, so missing triggers are re-created before the check | Open the DB raw for `integrity`/`guard`; report missing triggers | The check can detect tampering | P0 | XS | — | none | CLI path without `init_db` | none | Test: drop a trigger, `fil integrity` exits 1 | new pytest | A9 |
| F-03 | Freeze settled-bet fields (QA-1 + RK-2 clause) | `virtual_bets.payout/profit/settled_at` are mutable after settlement (`db.py:555-594`), and ROI reads them (`stats.py:25`) | Triggers block updates once `status ≠ pending`; allow `closing_price`/`clv` one NULL→value change; integrity cross-checks `virtual_bets.payout = settlements.payout` for both engines; make `model_versions.params` immutable | A ledger that cannot be silently rewritten | P0 | S | F-02 | none | SQLite triggers, integrity rule | breaks a legitimate correction path (handled by H-1 adjustment entries) | Tests: update payout after settlement → abort; first CLV fill OK, second → abort; mismatch → integrity fails | pytest + prod `fil integrity` | A9 |
| F-04 | Mobile disclaimer; no EV on flagged odds (UX-1, UX-5) | `styles.css:83` hides "SIMULATION ONLY" on mobile; ODDS ERROR rows still show EV | Always show the disclaimer and freshness; render "—" for EV on flagged rows | Compliance; no misleading value | P0 (UX-5 part P1) | XS | — | none | CSS/TSX | none | Playwright at 390 px finds the disclaimer; 0 EV values on flagged rows | Playwright smoke | A8 |
| F-05 | Odds API error masking (DP-3, QA-16) | `collect.py:121-125` calls `mark_success` after `mark_error`, so the circuit breaker never opens | Call `mark_success` only on success; a 429 doesn't reset the counter | Real provider health; quota protection | P1 | XS | — | none | provider code | none | Test: 3 failed runs → circuit open | pytest | A5 / A9 |
| F-06 | Settlement edge cases (RK-7, RK-8, QA-6, QA-7) | Postponement ordering; Engine B lacks integrity parity; `merge_duplicates` ignores `eb_*` rows; corrections after settlement not detected | Fix ordering; integrity covers `eb_*`; FK guard in merge; flag score changes after settlement | Correct ledgers in rare cases | P2 | S | F-03, J-5 | none | integrity + merge code | merge regressions | Tests for each case | pytest | A7 / A9 |
| F-07 | Fix `capabilities["lineups"]=True` and the `others.py:182` text (LV-11, LV-10) | The live adapter claims lineups and a status string says "not yet implemented" | Correct the capability flags and text | Truthful provider status | P1 | XS | — | none | code strings | none | API and coverage page show the correct status | pytest + page check | A5 |
| F-08 | Date-dependent test failure (found 08:05 UTC while the council PR was in CI) | `tests/test_system.py:132` requires 1X2 probabilities to sum to 1 within 1e-6, but they are stored rounded to 5 dp (`pipeline.py:89`). Today's synthetic fixture gives 1.00001. It fails on `main` @ `3a1ead6` too, so it is unrelated to the docs-only PR #10 | Re-normalise after rounding (largest-remainder), or assert within 5e-5. Pin the test's clock | Green, deterministic CI | P0 | XS | — | none | pipeline rounding + test | none | Test passes on any date (injected `now`) | pytest on 3 fixed dates | A9 |

### Category 2 — Reliability

| ID | Title | Problem | Proposed solution | Expected benefit | Pri | Effort | Deps | Data req. | Technical req. | Risks | Acceptance criteria | Validation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R-01 | Prove schedules and alert (OP-1, OP-4, PM-3, QA-10, OP-9) | No scheduled-run history; failure mail goes to a noreply cron author; schedules auto-disable after 60 idle days | A step opens or updates a GitHub issue on failure, and when no run has succeeded in 8 h; record the schedule delay in the run report; **owner re-saves the cron line once** | Outages are noticed within hours | P0 | S | — | job_runs | `issues: write` permission | issue noise (dedupe by label) | A forced failure opens exactly 1 issue; ≥ 20 consecutive scheduled runs observed | Actions history | A10 |
| R-02 | Atomic persist (QA-4, OP-5) | The manifest can be uploaded before the DB; no checksum | Upload the DB first and the manifest last, with sha256; verify after upload; an explicit `reset` dispatch input replaces the manual procedure | No guard deadlock, no torn state | P1 | S | F-01 | none | workflow + guard | — | A killed upload leaves the previous pair valid; restore verifies sha256 | CI simulation | A10 |
| R-03 | Concurrency queue and staggered minutes (OP-3, LV-7 stagger) | A live run can cancel a queued 3-hourly run | `queue: max` (in the official GitHub docs; untested here); live minutes `7,27,47`, 3-hourly `52` | No lost prediction windows | P1 | XS | — | none | workflow | `queue: max` may behave unexpectedly | 0 `cancelled` runs over 14 days | Actions history | A10 |
| R-04 | Least-privilege token (QA-13, OP-14) | Job-wide `GH_TOKEN` can delete the only backups | Pass the token only to the persist and publish steps; pass inputs via `env:` | Smaller blast radius | P1 | S | — | none | workflow | — | Other steps lack `GH_TOKEN` (grep in CI) | CI lint | A9 |
| R-05 | Quota guard before any key (DP-1, LV-6) | Odds API ≈ 290 credits/day against 500/month; API-Football up to 156–192/day against 100/day | Persisted per-provider budget (`quota_info`); the live adapter goes through `Provider.get`; refuse to start when the budget is spent. **No new key until merged** | Free plans are not exhausted | P1 | S | F-05 | none | provider base | — | Simulated 101st request refused; budget persists across runs | pytest | A5 |
| R-06 | Honest backups and drills (OP-6/7/10, QA-9/15) | The backup health signal checks runner-local files; no restore drill; ~158 GB of artifacts | Health reads release assets; weekly restore drill job; 7-day artifact retention; owner's monthly off-GitHub copy | Recoverability is proven | P2 | S | R-02 | none | workflow | — | The drill restores and passes integrity weekly | Actions history | A10 |

### Category 3 — Data

| ID | Title | Problem | Proposed solution | Expected benefit | Pri | Effort | Deps | Data req. | Technical req. | Risks | Acceptance criteria | Validation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D-01 | Pre-registered protocol and append-only ledger (RK-1, RK-9, GR-1) | Nobody outside can verify predictions were made before kickoff (gh-pages is force-pushed) | Commit `PROTOCOL.md` with a rule hash and a burn-in window; a daily normal commit appends new predictions (JSONL with hash chain); OpenTimestamps optional | Verifiable track record | P1 | S | F-01 | predictions | workflow commit step (`contents: write`) | repository growth (~MB/year) | ≥ 25 daily ledger commits; hash chain validates | script check in CI | A7 / A11 |
| D-02a | "Isolated rating pool" label (DS-1 interim) | UCL/UEL/UECL teams are disconnected from domestic twins | Label Engine B UEFA predictions as such | Honest presentation now | P1 | XS | — | none | UI/API string | — | Label shown on all 13 UCL insights | Playwright | A2 / A8 |
| D-02 | Team identity (DS-1, DS-2, DS-3) | 135 "Europe" teams; Andorra national team merged with FC Andorra (`teamnames.py:62`); "athletic" → Atlético; 7 duplicate fixtures | Link to domestic twins by name and country; split team 217; fix aliases; integrity rule for duplicates | Correct ratings for cups; clean data before tuning | P1 | M | F-03 | fixtures, teams | merge script + tests | wrong merges (needs a review list) | 0 duplicate fixtures; ≥ 45 UEFA teams linked; Andorra split | integrity + pytest | A2 |
| D-03 | Redistribution terms (DP-10) | ~348k football-data.co.uk odds rows republished in a public release | Record terms for each source; if unclear, publish predictions and results only | Legal safety | P1 | XS | owner | none | docs + release step | — | `DATA_SOURCES.md` lists the terms per source | owner review | A5 / owner |
| D-04 | LICENSE, description, topics, content policy (GR-3, GR-7) | No licence; no policy against "tips" framing | Add a licence (owner's choice), repository metadata and `CONTENT_POLICY.md` | Clear reuse terms | P2 | XS | owner | none | docs | — | Files present | review | A11 |

### Category 4 — Model

| ID | Title | Problem | Proposed solution | Expected benefit | Pri | Effort | Deps | Data req. | Technical req. | Risks | Acceptance criteria | Validation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M-01 | Reproducible validation in prod (ML-1, RK-3, RK-11, DS-4) | Documented numbers came from a scratch DB; backtests bypass the live gates; hard-coded 80/70/36 values | Verify Monday's `eb_validation_runs` row; backtest replays the live gates; store git SHA, params and per-match rows; documentation quotes the DB | Claims match production | P1 | M | D-01 | history | validation code | — | Rerunning from the stored SHA reproduces the metrics to ±0.0005 | CI rerun | A3 / A7 |
| M-02 | Meaningful CLV (RK-2, RK-5, ML-5, QA-8) | Same-book CLV; random selection already shows +0.1–0.4%; BFE glitches | CLV against the power-de-vigged consensus close minus a random-selection baseline; BFE sanity filter; store `reference_book` | A realistic edge metric (power ~125–350 bets) | P1 | M | F-03 | closing odds | value/settlement code | — | Random-selection CLV is ≈ 0 ± CI on the backtest | backtest | A7 |
| M-03 | Analyst honesty (MA-1/2/3/6/9) | "High confidence" in 102/130 reports; half-matchup comparison; hard-coded corners figures | Labels from absolute probability; confidence capped without validation; all four pairings; effects ≥ 10% only; cross-league flag; figures read from validation | Trustworthy text | P1 | M | M-01 | eb predictions | insights.py | blander text | "High confidence" in ≤ 15% of reports; tests per label rule | pytest + sample audit | A4 |
| M-04 | Tuning and promotion priors (ML-2/3/7, DS-5/6) | Engine B cold-starts promoted teams; parameters not tuned | Tune on a pre-2025 period; judge only on a post-freeze forward holdout of ≥ 1,500 matches; promotion prior from the league below | Possible ΔLL gains (expected small) | P2 | M | D-02, D-01 | history | validation | overfitting | Forward-holdout ΔLL CI excludes 0, otherwise reject | walk-forward | A3 |

### Category 5 — Live data

| ID | Title | Problem | Proposed solution | Expected benefit | Pri | Effort | Deps | Data req. | Technical req. | Risks | Acceptance criteria | Validation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L-01 | Gate live runs (LV-3, OP-2, OP-8) | 39 live runs a day each move the 37.7 MB DB | Before restore, skip unless a covered match is in [kickoff−5, kickoff+150] min; persist only on change; no artifact | ~90% fewer heavy runs | P1 | S | R-03 | fixtures | workflow + small CLI check | missing a match (gate on a stored schedule) | Days without covered matches: 0 persisted live runs | Actions history | A6 / A10 |
| L-02 | Live phase expiry and isolation (LV-2, LV-4) | Finished matches show "live" for up to 3 h; one bad match rolls back the batch | Expire 45 min after the last snapshot; per-match transactions | Correct status | P1 | S | — | live snapshots | live.py | — | Tests for expiry and partial failure | pytest | A6 |
| L-03 | Honest freshness (LV-1, DP-4) | The browser never relabels; `provider_updated_at=now` (`live.py:175`) | Use the provider timestamp; the browser recomputes the label from age. **Release gate before `API_FOOTBALL_KEY`** | Badges are never stale | P1 | S | — | provider timestamps | live.py + UI | — | A snapshot older than 5 min is never shown as LIVE | pytest + Playwright | A6 / A5 |
| L-04 | API-Football one-day probe (DP-5) | Real coverage and quota unknown | After R-05 and L-03, the owner registers a free key; probe for one day | Facts instead of claims | P2 | S | R-05, L-03, owner | — | — | quota | Probe report with real counts | report | A5 — **BLOCKED (owner)** |

### Category 6 — Dashboard

| ID | Title | Problem | Proposed solution | Expected benefit | Pri | Effort | Deps | Data req. | Technical req. | Risks | Acceptance criteria | Validation | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| U-01 | One provider truth (DP-2, LV-10, PM-8, UX-12) | Coverage says football-data.org "not configured"; "xG" used for model goal expectancy | Single provider-status source; rename to "expected goals (model)" | Trust | P1 | XS | F-07 | none | UI/API | — | No contradictory status across pages | Playwright | A5 / A8 |
| U-02 | Track Record page (PM-2, UX-7, RK-6, MA-10, UX-15) | No front-door proof; €0 tiles; Compare links to empty content | Page with A, B, closing market, naive and Elo-only (`component_probs`); n, CI, minimum-n gating; "no edge demonstrated" banner | The core differentiator | P1 | M | M-01, M-02, D-01 | evaluations | frontend + export | over-reading small n | No ROI shown below n = 300; CI always shown | Playwright + review | A1 / A8 |
| U-03 | Canonical match page and 4 sections (UX-2/3/4, PM-1) | 4 layouts with conflicting numbers; 12 nav items | One match page with source chips; Today · Match · Track Record · System | Clarity | P2 | M | U-02 | none | frontend | — | Each number labelled with its source; ≤ 4 top-level items | Playwright | A8 |
| U-04 | Performance and accessibility (UX-6/8/10, PM-9) | 692 KB bundle; 1.07 MB re-fetched every 2 min with `no-store`; overflow at 390 px | Lazy routes, cacheable polling, payload split, mobile tables, labels and contrast | Faster, usable on phones | P2 | M | — | none | frontend | — | Initial JS < 300 KB; no overflow at 390 px | Lighthouse + Playwright | A8 |
| U-05 | Daily briefing and follow teams (PM-5, PM-6) | No reason to return daily | "What changed" list from stored revisions; follow teams via localStorage | Return visits | P3 | S | U-03 | revisions | frontend | gambling-promo framing (no odds-move feed) | Briefing renders from real revisions | Playwright | A1 |

### Category 7 — Experimental (P3–P4, only after the 90-day exit criteria are met)
| ID | Title | Pri | Status | Note |
|---|---|---|---|---|
| X-01 | Form, strengths and xG panels (MA-4/5/8) | P3 | PROPOSED | after U-03; uses stored shots, corners, HT scores and xG for 2,033 matches |
| X-02 | Rest days and congestion (DS-7, D-2) | P3 | PROPOSED | computable from our own fixtures; must beat the baseline on a forward holdout |
| X-03 | Fit Engine B's market shrink (ML-4) | P3 | PROPOSED | only the shrink; no stacking |
| X-04 | Live in-play calibration (LV-8) | P4 | BLOCKED | needs a minute feed |
| X-05 | Player insights (MA-11), momentum (MA-13), goal timing (EB-7) | P4 | BLOCKED | no player or event data source |

---

### Recommendation register (2026-11-23)
All items above start at **PROPOSED**.

| ID | Status | Reason / note |
|---|---|---|
| PM-4 blended A+B+market headline | REJECTED | No measured gain from averaging or stacking (Agent 3); hides disagreement. Revisit only if X-03 passes |
| ClubElo comparator | REJECTED | Blocked host; needs a tunable draw model; the Elo baseline is already stored |
| Cloudflare / VM live stack (LV stages 2–5, OP-12) | REJECTED | No minute feed yet; second runtime; limits unverified |
| `live.json` / `live.db` split (LV-9) | REJECTED | Redundant after L-01 |
| Turning the live cron off entirely | REJECTED | Gating saves the same without losing the delayed feed. Fallback: delete the 4 colliding `:40` slots if L-01 is not done within 2 weeks |
| LV-7 00–03 UTC window | BLOCKED | No minute feed; quota |
| DS-8 Odds API for the benchmark | BLOCKED | Not needed (closing odds stored); may return after R-05 for pre-match coverage |
| ML-8 calibration layer, ML-10 gradient boosting, MA-14 LLM rephrasing | REJECTED | Measured null effect or complexity for show |
| GR-5 disagreement picks, PM-5 odds-move feed | REJECTED | Forking paths; gambling-promotion framing |
| GR-9 star targets, PM-7 calibration game | REJECTED | Vanity metrics while n = 0 |
| RK-10 Kelly staking | REJECTED | No demonstrated edge; flat €1 stake stays |
| DP-8 paid feeds | BLOCKED | Owner approval required; no justification before L-04 |
| DS-12 weather / manager changes | REJECTED | No reliable free source |
| `eb_validation_runs` empty treated as a bug | REJECTED | Not a defect: the step was added after the only weekly run; verify in M-01 |

### Comparison with previous reviews
This is the first council review. Overlaps with [`PRODUCT_BACKLOG.md`](PRODUCT_BACKLOG.md):

| Council ID | Earlier item |
|---|---|
| R-01 | A-7, M-1 |
| M-01 | I-7 |
| F-06 | H-1, J-5 |
| M-02 | F-2 |
| X-02 | D-2 |
| L-04 | LV-3 |
| R-03 | Q-3 (Actions updates) |

Earlier items keep their IDs; the council IDs reference them, so no duplicate issues are created.

## Register update 2026-11-25 (model council)
| Item | Status | Reason |
|---|---|---|
| Hyperparameter tuning of Engine A (decay, ridge, Elo K, cadence, newcomer prior, per-league weights) | REJECTED | 13 walk-forward variants all within ±0.001 LL |
| Market-implied ratings pooled into Engine A | REJECTED | Lagged copy of the market; breaks value-engine independence; no closing-line-value evidence |
| Clean reference prices (implausible BFE rows rejected) | IMPLEMENTED | `backend/fil/value.py` `plausible()`; 8 % cap measured against Pinnacle |
| SOT-xG proxy in Dixon-Coles | UNDER DISCUSSION | CI touches 0 against the production baseline; full ensemble test pending |
| UEFA team identity (council D-02) | APPROVED WITH CONDITIONS | Reversible migration, re-backtest, UCL predictor |
| Market shown as the benchmark in "My view" | IMPLEMENTED | Model weight vs the market ≈ 0 |
| 6-hourly council cycle (scheduled task) | IMPLEMENTED | Reports in `docs/council/cycles/` |
| SOT-xG proxy in Dixon-Coles (model 1.1.0) | IMPLEMENTED | Full Engine walk-forward dLL −0.00161 [−0.00312, −0.00019], n = 4,956, frozen coefficient — `docs/council/cycles/2026-11-25-1000-walkforward.md` |
| Corrected market gap published (clean prices) | IMPLEMENTED | A 1.1.0 is +0.0155 [+0.0117, +0.0192] worse than the clean market (was reported as +0.0126) |
| UEFA identity: reversible alias map + dry run | IN PROGRESS | `docs/data/UEFA_IDENTITY_DRYRUN.md`: 56 merges proposed; Athletic/Atleti alias, Como duplicate and Andorra/Monaco ids to fix first; apply only after a domestic re-backtest |
| 2026-11-25 12:51 cycle: watchdog started by the dispatcher | IMPLEMENTED (PR #19) | `GITHUB_TOKEN` runs never fire workflow_run; GitHub cron not firing |
| 2026-11-25 12:51 cycle: guessed "postponed" status | REJECTED | Would void bets; health-only "unresolved (round complete)" label instead |
| 2026-11-25 12:51 cycle: SOT proxy on non-walk-forward leagues | VERIFIED | dLL −0.00151 [−0.00270, −0.00044], n = 5,157 |
| 2026-11-25 12:51 cycle: My view fixes (match state, Engine B labels, equity) | IMPLEMENTED | Council UI agent |
| 2026-11-25 12:51 cycle: secondary-vs-secondary fixture merge, TheSportsDB results for lower leagues | DEFERRED | Alias-rewrite risk; ids unverified, 429s |
| 2026-11-25 18:51 cycle: idempotent, retried incident notifications; catch-up first | IMPLEMENTED | GraphQL errors delayed #21 by ~87 min |
| 2026-11-25 18:51 cycle: recovery-aware failure streak | IMPLEMENTED | #23 stayed open after a manual recovery run |
| 2026-11-25 18:51 cycle: per-endpoint TheSportsDB cache | IMPLEMENTED | 347 s cold runs; results must stay ≤ 2.5 h |
| 2026-11-25 18:51 cycle: My view mid-match state, postponed phase, Engine A version, readable quota | IMPLEMENTED | UI agent; matchState unit tests in CI |
| Promoted-team prior from second-tier data | REJECTED | Powered (n = 490 / 309) but null: ΔLL +0.00005 [−0.00107, +0.00125] |
| 2026-11-26 00:50 cycle: watchdog "Act on decision" failed on every run since 19:11 (pipefail + empty grep) | IMPLEMENTED | Fixed; tests now execute the step under `bash -e` |
| 2026-11-26 00:50 cycle: overdue-results fallback (TheSportsDB by-day, ITA2/ENG3/ENG4/SCO1) | IMPLEMENTED | Strict: explicit FT, same league, exact names, creates nothing, stops at 429; dry run 9/18 resolved |
| 2026-11-26 00:50 cycle: stale-cache answers in `provider_failures` | IMPLEMENTED | 8×429 were invisible in the run report |
| 2026-11-26 00:50 cycle: UI honesty (legacy €1 stakes, stale live score, forecast at 0 bets, late-results reason) | IMPLEMENTED | UI agent + skeptic |
| 2026-11-26 00:50 cycle: UCL duplicate fixtures / team identity, Engine B on UCL | DEFERRED | Owner gate: UEFA identity only after a domestic re-backtest |
| Rest-day adjustment | REJECTED | ΔLL +0.0009 [−0.0003, +0.0020] on 4,881 holdout matches |
| Pi-ratings + gradient boosting (owner request) | REJECTED | 1X2 LL 1.040 vs A 0.993; pool weight ≈ 0 |
| Engine A + B log-linear pool, OU2.5 | NOT APPLIED | ΔLL −0.0023 [−0.0035, −0.0012] but changes no bet; owner: keep situation as it is |
| 2026-11-26 06:50 cycle: fallback v2 (prefix/suffix names, per-fixture search, open bets first, 12 h day-list cache, budget counts network calls only, daily job) | IMPLEMENTED | 3 runs found 0 after the first; dry run 4/9 more, nothing created |
| 2026-11-26 06:50 cycle: one match-state rule on every page (statusNow/awaitingResult/Insights/Compare/TodayCard/History via matchState) | IMPLEMENTED | Pages disagreed; "in play / just played" never ended |
| 2026-11-26 06:50 cycle: legacy bankroll tag on /history; ROI and win rate hidden below 20 settled bets | IMPLEMENTED | "€99 → €502.33", "ROI +333 %" on one €1 bet |
| Shots-volume xG proxy (SOT + off-target + corners) | REJECTED | Underpowered: power 0.42–0.49 at the expected effect; not run |
| Team-news (lineups/absences) shadow feature | PROPOSED | 40 % of A's gap to the market is in the top-10 % disagreements; needs a data key (owner decision) |
| TheSportsDB 429 budget; gate for very late live crons; probably-postponed TheSportsDB-only fixtures in health | DEFERRED | Next cycle |
| 2026-11-26 06:50 cycle: TheSportsDB `searchevents.php` answers under "event" (not "events"), so every per-fixture search looked empty | IMPLEMENTED | Found while verifying the live run; parser test added; dry run then resolves 8 of 9 |
| 2026-11-26 12:50 cycle: log() inside an open write session (30 s wait, line lost) | IMPLEMENTED | Buffered and flushed after the outermost scope, with event time |
| 2026-11-26 12:50 cycle: TheSportsDB 429 cost (shared cool-down, no final-attempt sleep, 5 s spacing) | IMPLEMENTED | ~120 s lost per run; verify next cycle |
| 2026-11-26 12:50 cycle: dispatcher handover look-back (10 min, slots only) | IMPLEMENTED | Handover minute moves onto live slots daily |
| 2026-11-26 12:50 cycle: /upcoming on the shared match-state rule; catch-all route | IMPLEMENTED | UI agent clock-shift check |
| Overdue fallback v1+v2 accuracy | VERIFIED | 20/20 identical to football-data.co.uk (published 12:41), 0 conflicts |
| Temperature recalibration of A's 1X2 | REJECTED | ΔLL −0.0018 [−0.0037, +0.0001] |
| Engine B "cross-league rating" label for UEFA matches; UEL/UECL coverage in fixtures health | DEFERRED | Next cycle |
| 2026-11-26 18:50 cycle: provider down-marking (5 min), Retry-After lock-out respected (≤130 s, once per process), stale-first, 6.5 s TheSportsDB spacing | IMPLEMENTED | 15:42 fixtures took 739 s (outage + two 120 s lock-outs); the 12:50 change had saved nothing |
| 2026-11-26 12:50 cycle claim "0 rate-limit refusals after the fix" | CORRECTED | That run had a warm cache; 8 × 429 followed |
| 2026-11-26 18:50 cycle: Overview equity headline, open matches kept on today lists 12 h, health banner names its causes, "at placement" label | IMPLEMENTED | UI agent, clock-shifted checks |
| UEL/UECL coverage 6 of 36 (TheSportsDB cap) | RECORDED | Fixtures health to say so next cycle |
| ECC skills (owner request 2026-11-26): 17 adapted `ecc-*` project skills + `fil-guardrails` + `fil-council-cycle` + CLAUDE.md | IMPLEMENTED | Curated for this stack; MIT; no executable files; project rules take precedence |
| 2026-11-27 00:50 cycle: overdue fallback for UEL/UECL | IMPLEMENTED | 6/6 games of 26 Nov had no result source |
| 2026-11-27 00:50 cycle: Engine B "cross-league rating, low confidence" flag (display only) | IMPLEMENTED | All 13 UCL B predictions lack domestic history on ≥ 1 side |
| 2026-11-27 00:50 cycle: Analytics small-sample guard, /predictions bet note, badge clipping, friendly 404, open-bets empty state | IMPLEMENTED | UI agent |
| 2026-11-26 18:50 cycle: provider outage/lock-out handling | VERIFIED | 0 × 429 / 0 × 5xx since; fixtures step ~150 s = spacing |
| 2026-11-26 12:50 cycle: log() buffering | VERIFIED | First `collect` row persisted (bet #1 settlement) |
| UEFA→domestic id mapping walk-forward (Engine B) | NO-GO (for now) | Underpowered; needs a curated alias table ≥ 80 % coverage |
| 2026-11-27 06:50 cycle: honest health (odds coverage gap DEGRADED with count; live idle; unmonitored backlog out of the stale alarm) | IMPLEMENTED | UNKNOWN odds while 0/91 weekend fixtures had odds; live DEGRADED every night; EGY1/RSA1 noise |
| Weekend odds gap (football-data.co.uk not yet published; no Odds API key) | RECORDED | No paid service or new account without the owner; no bets possible until odds arrive |
| 2026-11-27 00:50 cycle items (UEFA fallback results, small-sample guard, bet notes, 404, low-conf. pills) | VERIFIED | 10/10 results web-verified; UI agent live checks |
| Live comparison with CIs and naive baseline on the site | PROPOSED | Models agent; next cycle |
| 2026-11-27 18:50 cycle: AH reference price now checked with plausible() (integrity bug: bet #3 used an 8.71 % BFE row) | IMPLEMENTED | Same clean-reference rule as every other Engine A market; bet #3 stays (immutable) |
| 2026-11-27 18:50 cycle: money display (equity headlines, open bets on forecast card, −€, AH away reason line) | IMPLEMENTED | First €10 bets exposed them |
| Engine B OU bets: model 13–18 pp above market, negative EV at the clean price; B's own ref rule allows BFE ≤ 15 % | RECORDED FOR OWNER | Betting rules frozen; CFO paused; no change |
| 2026-11-27 06:50 cycle honest health | VERIFIED | Live: odds HEALTHY, live idle, backlog listed |
| 12:50 cycle | MISSED | Session worker restart; covered by the 18:50 cycle |
| Backtest re-run after the AH reference fix | VERIFIED | 40→38 bets, ROI −29.7 %→−25.9 % (CI incl. 0); the 2 dropped AH bets both lost; 1X2/OU unchanged |
| 2026-11-28 00:50 cycle: Engine B small-sample guard, − sign in %, stake/return on open bets, Engine A bets on match pages | IMPLEMENTED | UI agent |
