# Agent 9 — QA, Reliability and Security Engineer

## 1. Current situation
Reviewed commit `3a1ead6`. The backend suite passes: `110 passed in 192.84s`, exit 0 (97 test functions, some parametrized; log at `scratchpad/council/agent09_pytest.txt`). I ran a read-only integrity check on a copy of the prod DB: `check_database` → `ok: true, problems: []`, `PRAGMA quick_check = ok`, 0 FK violations, 30 triggers present, and `guard_replace` against its own manifest → `(True, 'ok')`.

The production ledgers have never been exercised. The DB holds **0 virtual_bets, 0 eb_bets, 0 settlements, 0 eb_live_snapshots, 0 eb_evaluations and 0 eb_validation_runs**. All 121 Engine A predictions are `NO_BET`, all 621 value_assessments have `qualifies=0`, and 0 predictions are evaluated yet. Settlement, CLV and bankroll code is therefore verified only by unit tests, not by production data. As of about 01:50 UTC, `GET /actions/runs?event=schedule` returns `total_count 0`. The 00:40 cron did not fire, so scheduled operation is still unproven.

## 2. Evidence from the repository
- **Schema management:** `db.py:645-650`. `init_db` = `create_all` + `CREATE TRIGGER IF NOT EXISTS`. There is no ALTER, no `user_version` and no Alembic (grep returns nothing). The only "migration" test adds whole missing tables (`test_engine_b.py:322`). Because triggers use `IF NOT EXISTS`, changing an `IMMUTABLE` column list (`db.py:547`) never updates triggers already in an existing DB.
- **Mutable columns (probed on a rolled-back copy):**
  - ALLOWED: `UPDATE predictions SET eval_brier, eval_correct, evaluated, revision_reason`, `UPDATE fixtures SET home_goals`, `UPDATE model_versions/eb_model_versions SET params`, `DELETE FROM result_observations`, `DELETE FROM job_runs`.
  - BLOCKED: `predictions.probs`, `eb_predictions.*`.
  - `virtual_bets.payout/profit/settled_at/closing_price/clv` (and the same columns on eb_bets) are outside the trigger column lists (`db.py:556-558, 569-572`). `trg_*_no_resettle` only fires `OF status` (`db.py:591-598`), so a settled bet's payout and profit can be rewritten.
- **CLI masks missing triggers:** every CLI command except `guard` and `restore` calls `init_db()` first (`cli.py:55-63`). As a result, `python -m fil integrity` in the workflow restore step (`autopilot.yml:72`) re-creates deleted triggers before checking for them. Only `guard` (`cli.py:47-53`) inspects the raw file.
- **Workflow failure path:** if the restore step exits 1, the later steps still run because they use `if: always()`.
  - Persist exits early (no `data/fil.db`), which is correct.
  - But `Export static dashboard` (`autopilot.yml:125-127`) runs `init_db()` and creates an **empty** DB. It then exports, and `git push -f` publishes an empty dashboard over the good one (`:128-137`).
  - A partially failed `export_static` (`cli.py:118-150` copies the frontend first, then writes JSON) is also force-pushed.
- **Persist ordering:** `gh release upload db-latest data/fil.db.gz data/manifest.json`. On the live release, manifest.json was updated at 00:28:10 and fil.db.gz at 00:28:11. If the DB upload fails after the manifest upload, the next run compares an older DB to a newer manifest, and the guard refuses every run until someone fixes it by hand.
- **Guard coverage:** `integrity.py:105-117` checks only row counts and never content. Content can change while counts stay the same. `odds_observations`, `fixtures`, `result_observations`, `eb_evaluations`, `eb_validation_runs`, `model_versions` and `job_runs` are not protected from shrinking. With no previous manifest it allows the replace (`:102-103`).
- **Backups:** `db-latest` (37.7 MB gz) and `db-backups` (`fil-20261122/23.db.gz`) are both releases of the **same repo**, as are the workflow artifacts. There is no off-repo copy. The job token has `contents: write` (`autopilot.yml:25-26`), which can delete releases. `backup.backup(verify=True)` in the daily job writes to the runner's local `backup_dir`, which is thrown away when the run ends, yet health reports `backup: HEALTHY` (live `health_detail.json`).
- **Job lease:** `jobs.py:122-134` is a SELECT-then-INSERT with no `BEGIN IMMEDIATE`, so two processes can race. `recover_stale_runs` is called only by the in-process scheduler (`scheduler.py:43`), not by CLI `fil job`. If a run hits the 60-min `timeout-minutes` after inserting `running`, the always() persist step saves that row, and every run for 90 minutes is `skipped` and exits 0 (`cli.py:76-78`). The `timeout_s` check runs only between steps (`jobs.py:159`).
- **Duplicate merge vs Engine B:** `merge_duplicates` (`ingest.py:282-331`) skips fixtures that have Engine A predictions, bets or odds. It ignores `eb_predictions`, `eb_bets`, `eb_live_snapshots` and `match_stats`, then calls `s.delete(d)`. With `foreign_keys=ON` (`db.py:637`) plus the eb no-delete triggers, the transaction would abort. `PRIMARY_SOURCES = {"football_data_uk","intl_results"}` (`ingest.py:23`), so football_data_org fixtures count as "secondary".
  - Prod DB: 109 eb-predicted secondary fixtures, 13 of them with no Engine A prediction and no odds. None is a merge candidate today, so the bug is latent.
  - Merge-path fragility is already proven in prod: job_runs #3 and #5 failed with `UNIQUE constraint failed: team_aliases…` and `…result_observations…` (system_logs 6, 11).
- **Result corrections after settlement:** `reconcile` (`ingest.py:222-265`) takes the latest observation per source and overwrites `fixtures.home_goals`. Settlements are immutable and nothing compares `settlements.home_goals` with the current fixture score. A correction is silently ignored.
  - A single source is enough to mark a result as "verified".
  - AET: football-data.org `regularTime` is used (`football_data_org.py:189-195`), which is correct and tested (`test_extra_time_uses_90_minute_score_without_conflict`).
  - Abandoned matches are voided 48h after kickoff (`betting.py:95-98`). The rule text says "VOID unless an official result is later reported", but a later result cannot reverse the void. There is no abandoned-match test.
- **Engine B CLV bug:** the closing-odds query has no `order_by` before `.first()` (`engine_b/betting.py:158-160`). Engine A orders by `retrieved_at desc` (`betting.py:66-68`). Engine B AH bets would also be priced with `f"{sel}25"`.
- **Provider layer:** `base.py:146-148` calls `float(Retry-After)`. An HTTP-date value raises a `ValueError` that is not caught (only `httpx.HTTPError` is). Any HTTP 200 body is cached before it is validated (`:159-160`). Stale cache is served after repeated 429s and 5xx errors, labelled `from_cache` with the file's mtime. That is honest, but not shown to users per record.
- **Secrets:** handled well.
  - Keys are scoped to the `Run` step only (`autopilot.yml:87-92`, tested by `test_workflow_passes_secret_only_to_run_step`).
  - `security.py` redacts env values, auth headers and `apiKey=` query parameters.
  - The admin endpoint uses `hmac.compare_digest` and is disabled without a token (`api.py:444-449`).
- **Supply chain and CI weaknesses:**
  - `requirements.txt` is fully unpinned (`fastapi>=0.110` …), and actions are pinned by tag, not SHA. The job running unpinned PyPI code holds `GH_TOKEN` with contents:write (job-level env, `autopilot.yml:39`).
  - `${{ github.event.inputs.job }}` and `inputs.tag/target` are interpolated straight into shell (`autopilot.yml:76`, `release.yml:23-31`). Only users with write access can trigger this, so the risk is low.
  - `main` is not protected (API: "Branch not protected").
  - CI (`ci.yml`) does not run `frontend/e2e/smoke.cjs`.
- **Reproducibility:** `model_versions.params` holds only hyperparameters (`fil-ensemble 1.0.0`, `eb-insights 1.0.0`). Fitted coefficients and the code SHA are not stored, and the model is retrained daily under the same version id. Engine B stores a feature snapshot and `data_cutoff`, and Engine A stores `inputs` (Elo, form, odds ids). Replaying a prediction still requires refitting on a mutable `fixtures` table.
- **Leakage:** both engines filter `kickoff_utc < before` (`models/engine.py:35-36`, `engine_b/features.py:36-37`). Prod checks found 0 predictions created at or after kickoff, 0 `data_cutoff > created_at`, and 0 kickoff mismatches against fixtures.
- **Stale banner:** `main.tsx:29-41` compares `computed_at` (ISO with `Z`, verified live) to the client clock and flags data older than 8h. It works even when Actions stop, which is good. Health components are judged on step success: `settlement: HEALTHY` even though nothing has ever been settled.

## 3. What is working well
- The fail-closed restore and the shrink guard work as intended (verified on prod).
- Append-only tables are protected by DB triggers, and a DB-level pre-kickoff trigger blocks late bets.
- The bankroll chain is reconciled.
- Extra-time handling is correct.
- Conflicting results keep bets pending.
- The provider layer has a circuit breaker, rate-header throttling and tests for 429, timeouts and malformed responses.
- Secret scoping is tested.
- The engines are separated, and each step's failure is isolated.

## 4. What is weak or missing
- No schema versioning.
- Trigger column lists can silently drift.
- Settlement payout and profit, evaluation columns and model params are mutable.
- No detection of drift between settlements and corrected results.
- Duplicate merging ignores Engine B rows.
- The CLI path has no recovery for stale leases.
- A broken or empty dashboard can be force-pushed over a good one.
- No off-repo backup, no restore drill and no alerting (only GitHub's default failure e-mail). There is no dead-man's switch for "cron never fired". The STALE banner is passive.
- **Missing test scenarios:**
  1. `merge_duplicates` on a fixture that has eb_predictions.
  2. Result corrected after settlement.
  3. Abandoned match, then a later official result.
  4. Abandoned match with a partial score.
  5. Fixture rescheduled earlier than the bet's kickoff.
  6. Settled bet payout or profit UPDATE, which should be blocked.
  7. `fil integrity` reports missing triggers instead of re-creating them.
  8. Workflow with a restore failure, which must not publish an empty site.
  9. Manifest/DB upload mismatch.
  10. CLI run killed while holding the lease.
  11. Two processes acquiring the lease at the same moment.
  12. Retry-After given as an HTTP-date.
  13. HTML error page returned with HTTP 200, then cached.
  14. Engine B closing-price selection.
  15. A schema column added to an existing prod-shaped DB.
  16. Frontend e2e in CI.
  17. DST/kickoff changes for EB bets.
  18. Engine B integrity: payouts reconcile, no late pre-match bets, no settled bet without a settlement.

## 5. Important risks
1. **Silent audit-trail weakening.** Settled payouts and evaluation metrics can be rewritten by any future bug, and `fil integrity` hides missing triggers. This undermines the product's core claim of an immutable track record.
2. **A bad dashboard published after a failed restore or export.** Users would see an empty "HEALTHY-less" site with no explanation.
3. **Operational wedge.** A non-atomic manifest/DB upload, or a persisted stale `running` lease, can block runs. The lease case makes runs exit 0, so nothing alerts.
4. **A latent FK abort in `merge_duplicates`.** Once triggered, the fixtures step fails on every run (non-critical, so the run only goes "partial").
5. **Single-repo backups,** reachable by one token or one account action.
6. **Unproven scheduling and settlement in production:** 0 scheduled runs and 0 bets.

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| QA-1 | Extend triggers: block UPDATE of `payout, profit, settled_at, closing_price, clv` once `OLD.status!='pending'` (virtual_bets, eb_bets). Block eval_* UPDATE once `evaluated=1`. Make `model_versions`/`eb_model_versions` params immutable. Add an integrity check that compares each trigger's stored SQL to the expected SQL. | PARTIALLY IMPLEMENTED | P0 | S | none | New tests: the UPDATEs raise; altering a trigger's SQL makes `check_database` fail |
| QA-2 | `fil integrity` must not call `init_db` before checking (check the raw file first). | MISSING | P0 | XS | none | Test: dropping a trigger, then `python -m fil integrity` → exit 1 |
| QA-3 | Workflow: skip export/publish when restore failed or `export_static` raised. Export to a temp dir and push only if all JSON files are written and `health.json` is present. | MISSING | P0 | S | none | Simulated restore failure leaves gh-pages unchanged (dry-run test of the step script) |
| QA-4 | Persist atomically: upload the DB first, then the manifest, and embed the DB's sha256 in the manifest. The guard verifies the hash pair and refuses when a manifest exists but is missing. | PARTIALLY IMPLEMENTED | P1 | S | none | Test: a mismatched pair is detected with a clear message; there is no "no previous manifest" pass while db-latest exists |
| QA-5 | CLI `fil job` clears its own stale `running` rows, uses `BEGIN IMMEDIATE` for the lease, and exits non-zero (or warns) on `skipped` for scheduled runs. | PARTIALLY IMPLEMENTED | P1 | S | none | Tests: a killed run does not block the next one; a concurrent lease yields one winner |
| QA-6 | `merge_duplicates` also skips fixtures referenced by eb_predictions, eb_bets, eb_live_snapshots or match_stats (or re-points them where allowed). | MISSING | P1 | XS | none | Test: an eb-predicted secondary duplicate does not abort the fixtures step |
| QA-7 | Detect result corrections: an integrity/health check flags settlements whose score ≠ the current fixture score, and logs a WARNING. Do not silently re-settle; record a correction note in the ledger. | MISSING | P1 | S | none | Test: correcting a score after settlement → health WARNING listing the bet id |
| QA-8 | Engine B closing price: add `order_by(retrieved_at.desc())` and handle AH. Add an Engine B payout-reconciliation and late-bet check to integrity. | PARTIALLY IMPLEMENTED | P2 | XS | none | Tests for CLV choice and Engine B reconciliation |
| QA-9 | Off-repo weekly backup (another free location the owner controls) plus a monthly restore drill run with `verify_backup`. | MISSING | P1 | M | owner choice of storage | Documented restore under 30 min; a drill result recorded in job_runs |
| QA-10 | Alerting: a workflow that opens or updates a GitHub Issue when an Autopilot run fails or is partial, and a daily dead-man check (no successful run in 8h → issue). | MISSING | P1 | S | none | A forced failure creates an issue within one run |
| QA-11 | Schema versioning: set `PRAGMA user_version` and an ordered list of migration functions run by `init_db`; a test upgrades a v2.0.0 DB copy. | MISSING | P2 | M | none | A column added in a test migration applies to a copy of prod.db and keeps the manifest |
| QA-12 | Reproducibility: store fitted parameters (or their hash plus artifact) and the git SHA per model fit; bump the version per retrain. | PARTIALLY IMPLEMENTED | P2 | M | storage size | Re-scoring a stored prediction from saved params gives identical probabilities (1e-9) |
| QA-13 | Hardening: pin requirements via a lock file and actions by SHA, move `GH_TOKEN` to the steps that need it, pass dispatch inputs via `env:`, protect `main`, and add the e2e smoke test to CI. | PARTIALLY IMPLEMENTED | P2 | S | owner (branch protection) | CI green with a lock file; `GH_TOKEN` absent from the Run step env |
| QA-14 | Provider: parse an HTTP-date Retry-After and validate the body (JSON parse or CSV header) before caching. | MISSING | P3 | XS | none | Tests for both cases |
| QA-15 | Health: "settlement"/"backup" components report "UNKNOWN (never exercised)" and "local-only" truthfully. | MISSING | P3 | XS | none | With 0 settlements the state is not HEALTHY |

## 7. Top 3 recommendations
1. **QA-1 + QA-2 (close the immutability gaps and make integrity honest).** The platform's credibility rests on an append-only record. Today a settled bet's payout and profit, the evaluation metrics and the model params are all writable, and the integrity command repairs missing triggers before looking for them. These are small trigger and CLI changes with clear tests, and they must land before the first real settlement happens.
2. **QA-3 + QA-4 + QA-5 (make the GitHub Actions persistence loop safe under failure).** The workflow is the whole production system. Three failure paths can publish an empty dashboard, wedge the guard, or silently skip runs for 90 minutes while exiting 0. Each fix is a few lines of shell or Python, and together they turn "fail-closed on restore" into "fail-closed end to end".
3. **QA-10 + QA-9 (alerting and off-repo backup).** No scheduled run has fired yet, and nothing notifies the owner if schedules never start, jobs go partial, or the repo's releases are lost. A GitHub Issue-based alert plus a dead-man check costs nothing. A second backup location outside the repo removes the single point of failure, and the owner chooses the location.
