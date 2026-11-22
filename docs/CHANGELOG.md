# Changelog

## 2026-11-22 — football-data.org integration
* New `providers/football_data_org.py` client: X-Auth-Token header, adaptive throttling from `X-Requests-Available-Minute`
  and `X-RequestCounter-Reset`, 429 backoff, retries with stale-cache fallback, invalid-token (HTTP 400) and plan-limit
  (HTTP 403) errors, malformed-response handling.
* Sync modes: quick every 3h (1 request), full daily (competitions + current-season matches + standings, ~25 requests),
  one-time Champions League backfill (2023–2025).
* New append-only `standings` table, `/api/standings`, league positions in match details.
* Extra-time matches settle on the 90-minute score (`finished_aet`) instead of conflicting with sources that report
  scores after extra time. Delayed in-play scores are never stored.
* Duplicate prevention: provider-id linking; no invented teams or fixtures in primary-owned leagues; stricter fuzzy
  matching (fixes "Paris Saint-Germain" → Paris FC); aliases learnt in one league can no longer capture a namesake in
  another.
* Security: global log redaction, redaction in DB logs, job errors and provider errors; the workflow passes secrets
  only to the Run step; secret-leak tests cover logs, the DB, exports, backups and the frontend source.
* Tests: 70 → 91.

## 2026-11-22 — reliability & transparency release
### Fixed
* Workflow could overwrite the production DB with the launch snapshot after a transient download failure. Restore now
  fails closed and a manifest guard refuses shrinking ledgers.
* One failing step aborted whole jobs (production crash in run #1). Jobs now run isolated steps and report PARTIAL.
* `restore()` failed with `disk I/O error` while connections were open. The engine is now disposed first and the restored
  DB is integrity-checked.
* Malformed CSV/JSON, HTML error pages, or a single bad date row could abort an import.
* Duplicate-fixture merge crash (unique constraint, foreign-key ordering), with a regression test.
* Lost bets now show the bankroll after settlement.
### Added
* Health model (HEALTHY/WARNING/FAILED/STALE/UNKNOWN), `/api/health_detail`, System Health page, STALE banner.
* `fil.integrity`: quick_check, foreign keys, trigger presence, bankroll-chain reconciliation, settlement/payout
  reconciliation, duplicates, invalid scores, late bets.
* Verified backups, dated `db-backups` release, CLI `integrity`, `manifest`, `guard`, `run-report`.
* Cross-process job lease, job timeout, per-run operational report in Actions run summaries.
* Provider circuit breaker. Import validation (impossible scores/dates, results for unstarted matches).
* Explanations built from model parameters (main factors, weakening factors, missing data, model/market disagreement,
  freshness).
* Odds sanity flags, an "ODDS ERROR" badge, and best value computed from clean prices only.
* "DATA COVERAGE ONLY" / "INSUFFICIENT DATA" labels. Date and team filters.
* Bet ledger shows bankroll before/after, reason and data quality.
* Backtest: ECE, bootstrap ROI 95% CI, by-season and probability-range reliability, an out-of-sample calibration
  check (not deployed: negligible gain).
* Docs: PRODUCT_AUDIT, PRODUCT_BACKLOG, ROADMAP, DATA_SOURCES, MODEL_VALIDATION, OPERATIONS, CHANGELOG.
* Tests: 50 → 70 backend tests (reliability, integrity, health, a lifecycle test that runs the real components through
  to the dashboard export).

## 2026-11-22 — initial release
Data layer, Dixon-Coles + Elo ensemble, value engine, virtual bankroll, settlement, scheduler, React dashboard, GitHub
Actions autopilot, GitHub Pages.
