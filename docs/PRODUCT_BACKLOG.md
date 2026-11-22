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
| J-1 | Fail-closed DB restore in Actions | Fallback could overwrite newer DB | — | DONE | run fails if `db-latest` exists but download fails | workflow code; first scheduled run pending |
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
| B-3 | football-data.org / Odds API activation | More books & UEFA | API keys | BLOCKED | keys in secrets → provider HEALTHY | — |
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
