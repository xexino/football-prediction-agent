# Product backlog (source of truth)

Status values: **DONE** (implemented + verified), **PARTIAL**, **TODO**, **BLOCKED**. Nothing is DONE unless the
verification column was actually performed. Updated 2026-11-22.

## P0 — Critical foundation

| ID | Task | Reason | Deps | Status | Acceptance criteria | Verification |
|---|---|---|---|---|---|---|
| A-1 | Isolated job steps, critical-step classification, PARTIAL status | One crash stopped settlement/predictions | — | DONE | failing non-critical step does not stop others | `test_failed_step_does_not_stop_others`; live run reports |
| A-2 | Cross-process job lease + stale-run recovery | Server and CLI could overlap | A-1 | DONE | second runner skipped while lease live | `test_db_lease_prevents_cross_process_overlap` |
| A-3 | Job timeout control | Runaway jobs | A-1 | DONE | remaining steps skipped after 45 min | code review + CLI default `timeout_s=45*60` |
| A-4 | Per-run operational report | Visibility | A-1 | DONE | report stored + Actions step summary | live runs #7–#9 on prod copy |
| A-5 | Health model HEALTHY/WARNING/FAILED/STALE/UNKNOWN | "exit 0" ≠ healthy | A-1 | DONE | freshness-based states, overall = worst critical | `test_health_states`, `test_health_collection_failed_when_provider_erroring` |
| A-6 | Stale snapshot banner on static dashboard | Never show stale data as current | A-5 | DONE | banner if export > 8h old or health FAILED/STALE | build + Playwright |
| J-1 | Fail-closed DB restore in Actions | Fallback could overwrite newer DB | — | DONE | run fails if `db-latest` exists but download fails | Autopilot run #3 restored from `db-latest`, guard OK, persisted, dated backup `fil-20261122.db.gz` + `manifest.json` published |
| J-2 | Manifest guard before persisting DB | Prevent ledger loss | J-1 | DONE | refuse if immutable tables shrink or integrity fails | `test_guard_refuses_shrinking_ledger` |
| J-3 | Integrity checks (quick_check, FK, triggers, bankroll chain, settlements, duplicates, scores) | Corruption detection | — | DONE | `python -m fil integrity` exits 1 on problems | `test_integrity_detects_broken_bankroll_chain`; prod DB ok |
| J-4 | Verified backups + restore + dated backup release | Backups must be restorable | J-3 | DONE | backup restored into temp DB and checked; restore re-checks | `test_backup_and_restore`, `test_backup_verification_catches_corruption` |
| J-5 | Schema migration framework | Future column changes | — | TODO | versioned migrations, tested upgrade from current DB | — |
| H-1 | Result correction after settlement | Corrected scores | J-5 | TODO | correction recorded as adjustment entry, original kept | — |
| A-7 | Observe first scheduled Actions runs | Scheduling unverified | — | TODO | ≥3 consecutive scheduled runs succeed | Actions history |

## P1 — Prediction quality & data intelligence

| ID | Task | Reason | Deps | Status | Acceptance | Verification |
|---|---|---|---|---|---|---|
| B-1 | Provider circuit breaker | Repeated failures waste runs | — | DONE | open after 3 failed runs, 6h cooldown | `test_circuit_breaker_*`, `test_collect_fixtures_skips_open_circuit` |
| B-2 | Malformed-response handling, per-row validation | One bad row aborted imports | — | DONE | ProviderError / row skipped + counted | `test_malformed_responses_raise_provider_error`, `test_invalid_records_rejected` |
| F-1 | Odds sanity flags + clean best value in UI | +170% "value" from corrupt prices | — | DONE | suspect books flagged, excluded from best value | Playwright + screenshot |
| I-1 | ECE, bootstrap ROI CI, by-season, probability-range tables | Rigour | — | DONE | stored in backtest results, shown in Analytics | prod backtest run |
| E-4 | Probability calibration (power) with out-of-sample check | Under-confident favourites | I-1 | PARTIAL | adopt only if 2nd-half log loss improves materially | measured −0.0002 → not adopted |
| I-6 | Re-evaluate 1X2 value betting at ≥100 backtest bets | Weakest segment | — | TODO | decision documented with CI | — |
| I-2 | Simple-Poisson baseline in backtest | Prompted baseline set | — | TODO | metric row added | — |
| F-2 | Closing-line value report on live bets | Edge evidence | first bets | PARTIAL | CLV per bet stored; aggregate shown | needs settled bets |
| B-3a | football-data.org integration (fixtures, results, standings, CL history) | UEFA + cross-checks | key | DONE (code) | verified with real token; live sync in Actions once secret set | real API probe + 91 tests |
| B-3b | The Odds API activation | More bookmakers | key | BLOCKED | key in secrets → provider HEALTHY | — |
| B-4 | Champions League predictions (cup model: DC across leagues or Elo-only) | CL fixtures/results now available | B-3a | TODO | walk-forward validated before enabling | — |
| I-7 | Model registry: feature list + training-data hash per version | Traceability | J-5 | TODO | registry row has features + data cutoff | — |

## P2 — Coverage & football intelligence

| ID | Task | Status | Notes |
|---|---|---|---|
| C-1 | Coverage label "DATA COVERAGE ONLY — PREDICTIONS NOT ENABLED" / "INSUFFICIENT DATA" | DONE | API + Upcoming page |
| N-1 | African domestic leagues & CAF via a legitimate source | BLOCKED | needs API-Football key; TheSportsDB free tier too thin |
| N-2 | National-team model (Elo exists for national teams) + fixture source | TODO | needs upcoming fixtures source (football-data.org WC/EC with key) |
| D-1 | Team news / injuries / lineups | BLOCKED | API-Football adapter (key required) |
| D-2 | Rest days / congestion features (from our own fixtures) | TODO | computable without new sources |

## P3 — Product experience

| ID | Task | Status | Notes |
|---|---|---|---|
| L-1 | Explanations from model factors (main, weakening, missing, disagreement, freshness) | DONE | stored with new predictions; Upcoming + Predictions panels |
| K-1 | System Health page on health model, providers, step chips | DONE | Playwright |
| K-2 | Fixtures filters: date, team | DONE | Upcoming page |
| K-3 | Bet ledger: bankroll before/after, reason, data quality | DONE | `test_full_lifecycle_to_dashboard_export` |
| K-4 | Separate "Model Lab" page | TODO | backtest/model content currently on Analytics |
| M-1 | Notification channel beyond GitHub failure e-mails | TODO | e.g. issue on repeated FAILED health |
| P-2 | Prune odds of seasons older than training window | TODO | DB size |
| Q-3 | Upgrade Actions to Node 24 versions | TODO | deprecation warnings |


## v2.0.0 — Engine B / live data (2026-11-23)
| ID | Task | Status | Verification |
|---|---|---|---|
| EB-1 | Independent Engine B pipeline, model registry, immutable predictions with feature snapshots | DONE | test_engine_b.py, run on production copy (130 fixtures) |
| EB-2 | Goals, 1X2, BTTS, totals, correct score, clean sheets, first scorer | DONE | coherence tests; validation |
| EB-3 | Corners, cards, shots, shots on target, fouls models | DONE (corners: no skill vs baseline, labelled) | validation |
| EB-4 | AI Match Analyst reports | DONE | tests + screenshots |
| EB-5 | Engine B bankroll and ledger (1X2 disabled by evidence) | DONE | ledger/settlement tests |
| EB-6 | Walk-forward validation A vs B vs baselines vs market | DONE | eb_validation_runs |
| LV-1 | LiveProvider architecture, snapshots, events, live probabilities | DONE (mock-tested) | test_engine_b.py |
| LV-2 | football-data.org live (delayed) | DONE; no in-play match yet observed in a scheduled run | real request 2026-11-23 |
| LV-3 | API-Football live adapter | BLOCKED (needs `API_FOOTBALL_KEY`) | mock tests |
| CV-1 | Global coverage statuses and API-Football league mapping | DONE | coverage matrix page |
| EB-7 | Player markets, goal timing, possession, offsides | BLOCKED (provider) | marked unavailable |
| EB-8 | Optional LLM rephrasing layer | TODO (no key; deterministic reports work) | — |
| EB-9 | Improve Engine B 1X2 (stack with A? calibration) | TODO | must beat A out of sample |

## AI Product Council 2026-11-23
The council review re-prioritised open work; see [`AI_PRODUCT_COUNCIL_ROADMAP.md`](AI_PRODUCT_COUNCIL_ROADMAP.md). Corrections to this table:
* **EB-6** walk-forward validation: DONE on a scratch copy only. The production `eb_validation_runs` table is still empty (the step was added after the only weekly run), so the status is **PARTIAL until verified** (council M-01).
* **LV-3** API-Football: only the live adapter exists. There is no fixtures, lineups or injuries adapter, and no key may be added before the quota guard (council R-05).
* **A-7 / M-1** map to council R-01 (P0).
