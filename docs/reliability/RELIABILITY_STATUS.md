# Reliability status and scorecard

## Where the metrics live (collected from this release onward; history is not back-filled)
| Metric | Source |
|---|---|
| Scheduled slots expected / missed (24 h), runs completed / succeeded / failed / cancelled, success rate, consecutive critical failures, mean and longest duration, last critical success | Watchdog run summary (`.github/workflows/watchdog.yml`), computed from the GitHub run history by `backend/fil/ops/watchdog.py` |
| Per-run stage outcomes (restore, route, run, persist, export), job status, persistence result, dashboard-data freshness, partial flag | `data/ops_status.json` and `data/ops_history.json` (last 300 runs) on the published dashboard; System Health → "Autopilot pipeline" |
| Live GitHub run history and open incidents | System Health → "GitHub Actions — live run history" (read from the public GitHub API in the browser) |
| Database integrity, data freshness per domain, provider availability and error kind, live-data age | `data/health_detail.json` (`backend/fil/health.py`) |

## Baseline (2026-11-23, before this change; verified from the GitHub API)
| Measure | Value |
|---|---|
| Autopilot runs | 7 (6 success, 1 failure), of which **1 scheduled** |
| Critical scheduled slots missed, 22 Nov 21:40 – 23 Nov 09:40 UTC | 5 of 6 |
| CI | 38 runs, 9 failed, all from the date-dependent test F-08 |
| Mean / longest Autopilot duration | 6.3 / 11.8 min |
| Alerting | none (failure mail goes only to the last cron editor) |
| Dashboard after a failed restore | an empty, fresh-looking dashboard would have been published |

## Qualitative score
A numeric reliability score cannot be calculated honestly: there is not yet enough scheduled-run history.

| Capability | Before | After this change |
|---|---|---|
| Knows when it is broken | ✗ (only its own report, only if it ran) | ✓ independent watchdog reads the run history, including runs that never started |
| Knows why | partial (step table in the summary) | ✓ failure stage, provider error kind, persist reason, published on the dashboard |
| Recovers from safe failures | partial (provider retries) | ✓ bounded retries on download, upload and publish; stale lease cleared; previous dashboard kept |
| Preserves its data | good (shrink guard, triggers) | better: stale-asset check on restore, DB-first upload, raw pre-migration integrity, frozen settled-bet fields, atomic validated local restore |
| Tells its owner | ✗ | ✓ one de-duplicated GitHub issue per incident, closed on recovery |

**Remaining reliance:** GitHub's scheduler for both the Autopilot and the watchdog's hourly check (see runbook §17).
