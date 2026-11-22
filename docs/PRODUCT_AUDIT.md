# Product audit — Football Intelligence Lab

Audit date: 2026-11-22 (UTC). Based on the `main` branch at `71a3434`, the production database downloaded from the
`db-latest` release, and the GitHub Actions run history. Every status below was checked against code, tests or a run;
README claims were not taken on trust.

## 1. Operational state at audit time

| Item | Finding |
|---|---|
| Autopilot runs | 2 manual runs (scheduled runs had not fired yet: merge at 22:07 UTC, first 3-hourly slot 00:40 UTC). #1 **failed** (duplicate-merge crash), #2 succeeded after the fix |
| Production DB | `PRAGMA quick_check` ok. 56,141 fixtures, 347,658 odds snapshots, 28 predictions (all NO BET), 0 bets, 6 job runs (2 errors) |
| Dashboard | https://xexino.github.io/football-prediction-agent/ — **static snapshot**, refreshed by each autopilot run |
| Tests at audit start | 50 backend tests passing; Playwright smoke test passing |
| After this release | 70 backend tests, CI green on PR #3, Autopilot run #3 (daily) success, live health HEALTHY on all components |

## 2. Architecture map

```
GitHub Actions (cron 3h / daily / weekly)
  └─ restore DB (release db-latest) ─► python -m fil job <name> ─► guard + persist ─► export ─► gh-pages
backend/fil
  providers/  football-data.co.uk · TheSportsDB · intl results (GitHub) · football-data.org* · The Odds API* · API-Football* (stub)
  ingest.py   dedupe ±36h, team resolution (alias/fuzzy/anchor), result verification, append-only odds, validation
  models/     dixon_coles · elo + ordered logit · markets · calibration · engine (ensemble)
  quality.py  data-quality score · explain.py factors · value.py EV/de-vig/filters · betting.py ledger/settlement
  jobs.py     step runner (isolated steps, critical steps, leases, run reports) · scheduler.py (APScheduler, local mode)
  health.py   HEALTHY/WARNING/FAILED/STALE/UNKNOWN · integrity.py checks/guard · backup.py verified backups
  api.py      FastAPI JSON + static React dashboard · cli.py (serve, job, backtest, export-static, guard, …)
frontend/     React + TS + Recharts, 8 pages, static mode for GitHub Pages
```
`*` = needs a free API key (not configured).

## 3. Capability classification

Legend: **V** fully implemented and verified · **T** implemented but not sufficiently tested · **P** partial ·
**D** documented but not implemented · **M** missing · **B** blocked by external data.

| Capability | Status | Evidence / gap |
|---|---|---|
| Fixture discovery (football-data.co.uk, 38 leagues) | V | live runs, provider parser tests |
| Fixture discovery UEFA/CAF/African leagues | P/B | TheSportsDB free key returns ~1 next + 1 past event per league |
| Historical results + stats + xG | V | 47k matches; xG only for 2026/27 main leagues |
| Odds snapshots (pre-match & closing), append-only | V | triggers + `test_odds_snapshots_append_only` |
| Multi-source result verification / conflicts | V | conflict and agreement tests |
| Cross-provider fixture identity | V (after fix) | anchor matching + merge pass; crashed once in production (fixed, regression test) |
| Postponed/cancelled handling | T | unit test only; no real postponement observed yet |
| Data validation (scores, dates) | V (new) | `test_invalid_records_rejected` |
| Dixon-Coles / Elo / ensemble | V | gradient check, strength recovery, walk-forward backtest |
| Probability coherence | V | market-sum tests |
| Calibration | P | metrics + reliability tables + power calibration *check*; not deployed (no material gain) |
| Confidence score | V | separate from probability; components documented |
| Value engine / NO BET | V | rules tested; 28/28 live decisions NO BET |
| Odds data-error detection | V | cross-book and margin checks; UI badge |
| Virtual bankroll / stake / limits | V | DB triggers + tests |
| Settlement incl. AH quarter lines, void, conflicts | V | parametrised tests; idempotent re-run test |
| Result *corrections* after settlement | M | settled bets are immutable; a corrected result is flagged as conflict only if it arrives before settlement |
| Walk-forward validation, baselines, ECE, CI | V | `backtest.py`; latest run stored |
| Model registry | P | name/version/params/metrics; training cutoff stored per prediction; no feature list per version |
| Scheduler (local) | V | test + live server |
| Autonomous scheduling (Actions) | T | manual runs verified; scheduled triggers not yet observed |
| Step isolation / partial runs | V (new) | `test_failed_step_does_not_stop_others` |
| Cross-process job lease | V (new) | `test_db_lease_prevents_cross_process_overlap` |
| Retry / 429 / timeout / stale cache | V | reliability tests |
| Circuit breaker | V (new) | `test_circuit_breaker_opens_and_resets` |
| Health model (5 states) | V (new) | `test_health_states` |
| DB persistence guard | V (new) | `test_guard_refuses_shrinking_ledger`; workflow fails closed |
| Verified backups + restore | V (new) | restore-and-check in tests; dated backups release |
| Explanations from model factors | V (new) | `test_explanation_built_from_model_factors` |
| Team news / injuries / lineups | B | no free legitimate source; API-Football adapter not implemented |
| Live data | B | none connected; UI labels everything pre-match |
| Notifications | P | GitHub's failed-workflow e-mail + Actions run summary; no push channel |
| Dashboard (8 pages) | V | Playwright smoke test, mobile width check |

## 4. Weaknesses and risks found (and what was done)

| # | Finding | Severity | Action |
|---|---|---|---|
| 1 | If `db-latest` download failed transiently the workflow fell back to the launch snapshot and **overwrote** the release → silent loss of all predictions/bets since launch | P0 | Fixed: fail closed + manifest guard refusing shrinking ledgers |
| 2 | Monolithic jobs: one exception (merge crash) skipped settlement and predictions | P0 | Fixed: isolated steps, critical-step classification, PARTIAL status |
| 3 | "success" = no exception; no freshness model; static site could show old data as current | P0 | Fixed: health model + STALE banner using export age |
| 4 | Restore while connections open → `disk I/O error` | P0 | Fixed: engine disposed before restore; restore verified |
| 5 | Malformed CSV/JSON or one bad date row could abort a whole import | P1 | Fixed: ProviderError wrapping, per-row skip + counters |
| 6 | Corrupt bookmaker rows (e.g. 1.09/1.08/1.11) displayed as +170% "value" | P1 | Fixed in UI: clean best value + ODDS ERROR badge (bets were already blocked) |
| 7 | TheSportsDB 429s cost ~8 min per run | P1 | Fixed earlier: fewer calls; now circuit breaker too |
| 8 | Favourites under-predicted (60–70% bucket: 64.5% predicted vs 69.6% observed) | P1 | Measured; power calibration gives only −0.0002 log loss → not deployed; tracked |
| 9 | 1X2 value bets weakest segment in backtest (29 bets, ROI −45%, 95% CI −88%…+2%) | P1 | Logged; too few bets to act on; re-evaluate at ≥100 bets (backlog I-6) |
| 10 | Odds snapshots of historical seasons dominate DB size (~150 MB raw) | P3 | Acceptable today (37 MB compressed); backlog P-2 |
| 11 | Node 20 deprecation warnings in Actions | P3 | Backlog Q-3 |

## 5. External dependencies & limits

| Provider | Key | Limits | Risk |
|---|---|---|---|
| football-data.co.uk | none | polite use; updated ~2×/week | single primary source for odds/stats |
| TheSportsDB | public `123` | ~30 req/min, 1–15 events per call | low value; circuit breaker |
| martj42/international_results | none | GitHub raw | irregular updates |
| football-data.org | needed | 10 req/min, 12 competitions | not configured |
| The Odds API | needed | 500 credits/month | not configured |
| API-Football | needed | 100 req/day | not configured, adapter missing |
| GitHub Actions / Pages / Releases | — | public repo: free minutes; 2 GB per release asset | scheduled workflows are disabled after 60 days without repository activity |
