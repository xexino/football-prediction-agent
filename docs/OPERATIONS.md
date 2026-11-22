# Operations runbook

## Where things run
| Mode | What runs it | Dashboard |
|---|---|---|
| Production (autonomous) | GitHub Actions `autopilot.yml` | https://xexino.github.io/football-prediction-agent/ (static snapshot) |
| Local / any server | `scripts/start.sh` (FastAPI + in-process APScheduler) | http://localhost:8000 (live API) |

## Schedule (Actions, UTC)
| Cron | Job | Steps |
|---|---|---|
| `10 5 * * *` | daily | results → fixtures → international → **settle** → evaluate → retrain → **predict** → coverage → **integrity** → report → verified backup |
| `40 */3 * * *` | results + fixtures_odds | results → **settle** → evaluate; fixtures → **predict** |
| `25 6 * * 1` | weekly | walk-forward backtest → weekly report |

Steps in **bold** are critical: if one fails the run is FAILED. Any other failed step makes it PARTIAL, and the remaining
steps still run. Every run writes a report to `job_runs.summary.report` and to the Actions run summary.

## Persistence & safety
* **Latest database:** release `db-latest`, holding `fil.db.gz` and `manifest.json` (row counts of the immutable tables).
* **Restore fails closed.** If `db-latest` exists but cannot be downloaded after 4 attempts, the run stops. It never falls
  back to an older snapshot.
* **Guard.** Before upload, `python -m fil guard data/fil.db data/manifest.prev.json` refuses the database if:
  * the integrity check fails, or
  * any immutable table shrank (predictions, value assessments, bets, settlements, bankroll transactions).
* **Daily backups:** dated copies in the `db-backups` release (14 kept). Each run's database is also kept as a 90-day
  workflow artifact.
* **Dashboard always republished,** even when the job failed, so the System Health page shows the problem. The page shows a
  STALE banner if the snapshot is more than 8 h old.

## Health states
`HEALTHY` working and recent · `WARNING` degraded or late · `STALE` no successful update for too long ·
`FAILED` the last attempt failed or there is an integrity problem · `UNKNOWN` never ran or not configured.

| Component | Healthy if newer than | Warning until |
|---|---|---|
| Collection | 8 h | 30 h |
| Predictions | 8 h | 30 h |
| Settlement | 12 h | 36 h |
| Backups | 30 h | 54 h |
| Odds for upcoming fixtures | 72 h | 120 h |
| Scheduler (last run) | 7 h | 26 h |

The database component runs `integrity.check_database()` on every health computation.

## Common procedures
Run a job manually: Actions → Autopilot → Run workflow → `daily`, or locally:
```bash
cd backend && python -m fil job daily
```
Check integrity:
```bash
cd backend && python -m fil integrity
```
Get the latest production database:
```bash
gh release download db-latest -p fil.db.gz && gunzip fil.db.gz
```
Restore a backup locally (stops the server and re-checks integrity after restoring):
```bash
scripts/restore.sh data/backups/fil-<timestamp>.db.gz
```
Restore production from a dated backup: download it from the `db-backups` release, check it with
`python -m fil integrity`, then upload it as `fil.db.gz` to `db-latest` and delete `manifest.json` there. Removing the
manifest is a deliberate override of the shrink guard, so only do it on purpose.

## Failure handling
| Symptom | Meaning | Action |
|---|---|---|
| Actions e-mail "Autopilot failed" | a critical step failed or the guard refused | read the run summary; the database was **not** overwritten if the guard refused |
| Provider circuit OPEN | 3 consecutive failed runs | skipped for 6 h, then retried automatically |
| STALE banner | no successful refresh for over 8 h | check whether scheduled workflows are enabled (GitHub disables them after 60 days without repository activity) |

## Limits of the free infrastructure
* Actions schedules can start late under load.
* Runs are capped at 60 minutes (a typical run takes 2–8 minutes).
* Pages serves a static snapshot only, with no live API.
* The provider cache persists between runs through `actions/cache`.
