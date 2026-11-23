# Autopilot runbook

Repository: `xexino/football-prediction-agent`. Dashboard: <https://xexino.github.io/football-prediction-agent/>.
All commands assume the repository root unless they start with `cd backend`. `gh` is the GitHub CLI, authenticated as the owner.

## 1. How the Autopilot works
`.github/workflows/autopilot.yml` runs on GitHub-hosted runners. Each run goes through these stages:

| Stage | Step | What it does | On failure |
|---|---|---|---|
| restore | Restore database | Downloads `fil.db.gz` + `manifest.json` from release `db-latest` (4 tries, gzip-tested), runs `fil integrity --pre-migration`, `fil guard --pre-migration` (the file must not be older than its manifest), then `fil migrate` and the full `fil integrity` | Run fails. **No persist, no export.** The previous dashboard data stays published with a FAILED pipeline banner |
| route | Pick job | `python -m fil.ops.schedule` maps the cron string or the manual input to the job(s) (`backend/fil/ops/schedule.py`) | Unknown cron or job: run fails |
| run | Run | `python -m fil job <job> --status-out …` for each job | `error` fails the run. `partial` gives a warning annotation and pipeline state DEGRADED |
| persist | Persist database (guarded) | WAL checkpoint, `fil guard` (integrity check + immutable tables may not shrink), upload the DB **first** and the manifest **last** (3 tries each), dated daily backup in release `db-backups` (14 kept). Live runs that created no new records skip the upload | Run fails; `OPS_PERSIST` = `refused` or `failed` |
| export | Export static dashboard | `fil export-static site.new`, verifies `health.json` and `index.html`, then swaps it in | Run fails; the previous dashboard data is republished |
| status | Operational status | Writes `data/ops_status.json` and `data/ops_history.json` (last 300 runs, carried forward from the published site) | Always runs |
| publish | Publish dashboard | Force-pushes the site to `gh-pages` (3 tries) | Run fails; the watchdog notices |

The separate `.github/workflows/watchdog.yml` judges the run history itself. It runs after every Autopilot run, hourly at :17, and on demand.

## 2. Schedule and timezone reference
Cron in GitHub Actions is **UTC**, with no daylight-saving shift. Rome is UTC+1 in winter and UTC+2 in summer.

| Cron (UTC) | Job | Rome (winter / summer) | Criticality |
|---|---|---|---|
| `10 5 * * *` | daily | 06:10 / 07:10 | critical |
| `40 */3 * * *` | results,fixtures_odds | every 3 h at :40 (00:40, 03:40, …) | critical |
| `25 6 * * 1` | weekly | Monday 07:25 / 08:25 | critical |
| `7,27,47 11-23 * * *` | live | :07/:27/:47, 12:07–00:47 / 13:07–01:47 | best effort |

The routing table is `backend/fil/ops/schedule.py`. A test (`test_every_workflow_cron_is_routed_and_valid`) fails if the workflow and the table differ. GitHub may start scheduled runs late (77 min was observed) or skip them.

## 3. How to run jobs manually
```bash
gh workflow run autopilot.yml -f job=daily
```
```bash
gh workflow run autopilot.yml -f job=results,fixtures_odds
```
Allowed jobs: `daily, fixtures_odds, results, prematch_review, weekly, live, engine_b, backup, bootstrap`. Anything else is rejected at the route stage. You can also start a run from Actions → Autopilot → Run workflow.

Locally (your own copy, never the production asset):
```bash
cd backend && FIL_DB_PATH=../data/fil.db python -m fil job daily
```

## 4. How to identify a failed run
* **GitHub issue labelled `autopilot-incident`:** opened by the watchdog, which also comments when the problem changes and closes it on recovery. Watch the repository (Watch → Custom → Issues) to receive these by e-mail.
* **Dashboard banner:** "Pipeline FAILED — the last run failed at the *X* stage". The System Health page shows the stages, the last success, the last failure and the live GitHub run history.
* **Actions:**
  ```bash
  gh run list --workflow autopilot.yml --limit 20
  ```
  Each run's summary has a stage table (restore / route / run / persist / export / publish).
* **Watchdog decision for the latest evaluation:**
  ```bash
  gh run list --workflow watchdog.yml --limit 1
  ```
  Then open the run's summary.

Watchdog thresholds (in `backend/fil/ops/watchdog.py`):

| Threshold | Value | Why |
|---|---|---|
| No successful critical run for | > 8 h | Critical work runs every 3 h; 8 h means two cycles were lost, plus slack for delays |
| Scheduled run counted as missed after | 120 min | Delays of 77 min have been observed |
| Run counted as stuck after | 75 min | The job's own timeout is 60 min |
| Missed critical slots in 24 h | ≥ 2 → incident; 1 → DEGRADED only | |
| Consecutive live failures | ≥ 3 → incident | |
| Consecutive critical failures | any failed or cancelled → incident | |

## 5. How to inspect failure logs
```bash
gh run view <run-id> --log-failed
```
The run summary contains the stage table and `fil run-report --last 3` (per-step status, durations and errors; errors are redacted). Provider errors are classified in System Health → Providers (`rate_limited`, `auth_failed`, `unavailable`, `invalid_response`, `missing_credentials`).

## 6. Recovering from provider failures
* **What happens automatically:**
  * Transient HTTP errors are retried with backoff (`providers/base.py`, 3 attempts; 429 honours `Retry-After`, capped at 30 s).
  * After 3 failed runs the provider's circuit breaker opens for 6 h. This is now also true for The Odds API, where errors had been masked.
  * The other steps still run: provider steps are non-critical, so the run is PARTIAL.
* **`auth_failed`:** rotate the key (section 14).
* **`rate_limited`:** wait for the quota window to reset. Do not add more polling.
* **`unavailable`:** nothing to do. The circuit breaker and retries handle it, and stale cached data is labelled as such.
* **An empty provider response is never treated as "no fixtures".** A failure is recorded as an error with a kind, and the run is PARTIAL.

## 7. Recovering from a failed database restore
The run fails at the `restore` stage and nothing is persisted or exported. Check the log:

* **Download failed 4 times:** a GitHub outage. Re-run later:
  ```bash
  gh run rerun <run-id>
  ```
* **`integrity` failed:** the published asset is damaged. Do **not** delete it. Download it and inspect it:
  ```bash
  gh release download db-latest -p fil.db.gz -p manifest.json -D /tmp/fil
  ```
  ```bash
  gunzip -k /tmp/fil/fil.db.gz && cd backend && FIL_DB_PATH=/tmp/fil/fil.db python -m fil integrity --pre-migration
  ```
  Then restore the newest good dated backup (section 10).
* **`guard` refused (`immutable tables would shrink`):** the database asset is older than its manifest, typically because a previous upload was interrupted. Use the newest run artifact `fil-db-<run id>` (30 days) or a dated backup whose counts are ≥ the manifest. Compare counts with:
  ```bash
  cd backend && FIL_DB_PATH=<file> python -m fil manifest /dev/stdout
  ```

## 8. Recovering from a failed persist
* **`refused`:** the guard blocked a database that failed integrity checks or lost records. This is the safety net working. The previous `db-latest` is untouched. Find the cause in the run log, fix the code, re-run.
* **`failed`:** the upload failed after 3 tries.
  * If the log shows that `fil.db.gz` uploaded but `manifest.json` did not, the next run still restores correctly: the old manifest has lower or equal counts.
  * If neither uploaded, the next run uses the previous database; the work of the failed run is lost, but nothing older overwrites anything newer.
  * The run's artifact `fil-db-<run id>` holds the database.

## 9. How to validate backups
```bash
gh release download db-backups -p 'fil-20261123.db.gz' -D /tmp/fil
```
```bash
cd backend && python -c "from fil.backup import verify_backup; from pathlib import Path; print(verify_backup(Path('/tmp/fil/fil-20261123.db.gz')))"
```
`ok: true` means the backup decompresses and passes the full integrity check (quick_check, foreign keys, triggers, ledger chains, payout reconciliation, duplicates, scores).

## 10. How to restore a backup safely
1. Validate the backup (section 9).
2. Compare its counts with the current manifest:
   ```bash
   gh release download db-latest -p manifest.json -D /tmp/cur
   ```
   **Never publish a backup with fewer predictions, bets, settlements or bankroll transactions unless you accept losing those records.** If you do, write the decision down in an issue.
3. Publish it as the current database (the asset name must be exactly `fil.db.gz`):
   ```bash
   mkdir -p /tmp/up && cp /tmp/fil/fil-20261123.db.gz /tmp/up/fil.db.gz && gh release upload db-latest /tmp/up/fil.db.gz --clobber
   ```
   Then generate the matching manifest locally (`fil manifest`) and upload it **after** the database.
4. Run `gh workflow run autopilot.yml -f job=results` and confirm that the restore stage succeeds.

`python -m fil restore <file>` (local server) validates the candidate in a temporary file first. A failed restore leaves the current database untouched, and the previous file is kept as `*.before-restore-<time>.db`.

## 11. Diagnosing a stale dashboard
* **STALE SNAPSHOT banner** (data older than 8 h): no run has published.
  1. Check the live GitHub run history on System Health, or `gh run list --workflow autopilot.yml`.
  2. Check for an `autopilot-incident` issue.
  3. Check that Pages is set to deploy from `gh-pages` (Settings → Pages).
* **Pipeline banner says "previous snapshot":** the last run could not export (restore failed). See section 7.
* **Health components DEGRADED or STALE while the pipeline is HEALTHY:** the pipeline ran, but a data source has not delivered fresh data (e.g. football-data.co.uk publishes odds about twice a week). This is real information, not a pipeline fault.

## 12. Diagnosing live-feed failures
* **Free plans give delayed data.** football-data.org gives a delayed score and status with no minute. API-Football is configured only if `API_FOOTBALL_KEY` is set.
* **Labels decay in the viewer's browser:** LIVE becomes DELAYED after 3 min and STALE after 30 min. A match leaves the "live" tab 45 min after its last snapshot.
* **Live runs are best effort:** single failures make the watchdog DEGRADED; 3 in a row raise an incident.
* **To check the newest snapshot:** System Health → Live component.

## 13. Notification secrets
* **No secret is needed for the default channel.** The watchdog uses the built-in `GITHUB_TOKEN` (`issues: write`) to open and close `autopilot-incident` issues, and GitHub e-mails watchers.
* **Recommended owner action:** Watch the repository with "Issues" enabled.
* **Optional:** re-save `.github/workflows/autopilot.yml` from your own account once. GitHub sends failure e-mails for scheduled workflows to the user who last edited the cron line.
* **Not implemented:** external webhooks (Slack, e-mail API). They would need a new secret; none is configured, and none is assumed.

## 14. Rotating provider credentials
Settings → Secrets and variables → Actions → update `FOOTBALL_DATA_ORG_KEY` / `ODDS_API_KEY` / `API_FOOTBALL_KEY`. Then:
```bash
gh workflow run autopilot.yml -f job=fixtures_odds
```
The Run step prints only `configured` / `not configured`, never the value. Before adding `ODDS_API_KEY` or `API_FOOTBALL_KEY`, read the quota warning in `docs/PROVIDER_COMPARISON.md`. A quota guard (council R-05) is not implemented yet.

## 15. Safely re-running a job
All jobs are idempotent:
* predictions are revised only when inputs change;
* settlement skips settled bets, and triggers forbid re-settlement;
* ingestion de-duplicates by content hash.

Runs are serialised by the `autopilot` concurrency group. Re-run with:
```bash
gh run rerun <run-id>
```
Or dispatch the job again. A `running` lease left by a cancelled run is cleared automatically at the start of the next run (`FIL_SINGLE_RUNNER=1`).

## 16. Identifying duplicate or incomplete processing
* `fil integrity` reports:
  * duplicate fixtures;
  * bets without stake transactions;
  * settled bets without settlement rows;
  * payout mismatches between `virtual_bets` and `settlements`;
  * bankroll chain breaks.
* The step table of each run shows which steps did not run (`skipped: job timeout reached`) or failed.
* The pipeline state `DEGRADED` with `job status: partial` marks incomplete runs.

## 17. When manual intervention is required
* An `autopilot-incident` issue stays open for more than one cycle.
* A persist was `refused`.
* A restore failed because of integrity.
* An `auth_failed` provider.
* **The watchdog itself stops running.** It runs on GitHub's scheduler too, plus after every Autopilot run. If GitHub stops *all* scheduled workflows (for example after 60 days without repository activity), the watchdog's hourly check stops as well. Two mitigations:
  * any commit re-enables schedules;
  * optional: a free external uptime monitor polling <https://xexino.github.io/football-prediction-agent/data/ops_status.json>, alerting when `generated_at` is older than 8 h. This is not set up, because it needs an external account.

## 18. Rolling back a release
* Code:
  ```bash
  git revert <merge-commit>
  ```
  Then open and merge a PR. The database schema is backwards compatible: new triggers only restrict updates.
* To remove the new triggers (not recommended):
  ```sql
  DROP TRIGGER trg_bets_settled_frozen; DROP TRIGGER trg_bets_clv_once; DROP TRIGGER trg_eb_bets_settled_frozen; DROP TRIGGER trg_eb_bets_clv_once;
  ```
  Run this on a downloaded copy, then follow section 10.
* Releases are tagged by `.github/workflows/release.yml` (manual). Do not delete tags; publish a new patch release instead.
