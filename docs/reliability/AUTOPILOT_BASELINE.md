# Autopilot reliability baseline (audit of 2026-11-23)

Audited state: `main` @ `a65921d` (after PR #10). The run history was read from the GitHub REST API (public
repository, `actions/runs?per_page=100`) at 2026-11-23 ~09:40 UTC. Nothing below is estimated unless marked
**UNVERIFIED**.

## 1. Architecture (before this change)
* **One workflow, `.github/workflows/autopilot.yml`**, on free GitHub-hosted runners. The steps are:
  1. checkout, Python/Node setup, frontend build;
  2. restore `data/fil.db` from the release asset `db-latest` (fail-closed when the asset exists but cannot be downloaded);
  3. `python -m fil integrity`;
  4. pick the job from the cron string with an inline `case` statement;
  5. `python -m fil job <job>`;
  6. persist (`fil guard` → `fil manifest` → upload `fil.db.gz` and `manifest.json` in one `gh release upload`);
  7. upload a 90-day artifact;
  8. export the static dashboard;
  9. force-push `gh-pages`;
  10. write the step summary.

  Steps 6–10 ran with `if: always()`.
* **Backend jobs** (`backend/fil/jobs.py`) are lists of steps with a critical/non-critical flag:
  * a failure in a non-critical step makes the run PARTIAL, a critical failure makes it ERROR;
  * a DB lease (`job_runs` row with status `running`, 90 min) prevents overlap.
* **Health** (`backend/fil/health.py`) judges components by the age of their last *successful* work. The states were HEALTHY, WARNING, STALE, FAILED and UNKNOWN.
* **Database safety**:
  * SQLite triggers make predictions, settlements and ledgers immutable (`backend/fil/db.py`);
  * `fil guard` refuses to persist a database that fails integrity checks or whose immutable tables shrank (`backend/fil/integrity.py`).
* **CI** (`.github/workflows/ci.yml`): pytest plus the frontend build, on every push and pull request.

## 2. Schedules (as found)
| Cron (UTC) | Job | Notes |
|---|---|---|
| `10 5 * * *` | daily | 06:10 CET / 07:10 CEST (cron is UTC, no daylight-saving shift) |
| `40 */3 * * *` | results,fixtures_odds | the default branch of the inline `case`: **any unknown cron also ran this job** |
| `25 6 * * 1` | weekly | Monday |
| `*/20 11-23 * * *` | live | the `:40` minute coincides with the 3-hourly run in hours 12, 15, 18 and 21 |

## 3. Actual run history (verified)
| Workflow | Runs | Result |
|---|---|---|
| Autopilot | 7 | 6 success, 1 failure (run #1 on 2026-11-22, the duplicate-merge crash fixed in PR #2). **Only one run was scheduled**: [run #7](https://github.com/xexino/football-prediction-agent/actions/runs/45097471610) for the 00:40 slot, created 01:57:48Z (77 min late), success |
| CI | 38 | 29 success, **9 failure, all between 08:01 and 08:07 UTC on 2026-11-23, all the same test** |
| Release | 2 | 1 failure (403, fixed earlier by retargeting), 1 success |
| pages build and deployment | 7 | 7 success |

**The red runs in the owner's screenshot are CI runs, not Autopilot runs.**
* Every one fails `tests/test_system.py::test_pipeline_produces_valid_predictions`: 1X2 probabilities rounded to 5 dp summed to 1.00001.
* The input depends on the current date, so CI became red on 2026-11-23 for every commit, including `main` @ `3a1ead6` (verified locally).

**Missed schedules (verified):** between 2026-11-22 21:40 and 2026-11-23 09:40 UTC, these critical slots never started:
* 21:40 (3-hourly);
* 03:40 (3-hourly);
* 05:10 (daily);
* 06:25 (weekly);
* 06:40 (3-hourly).

No live slot was due yet (live polling starts at 11:00). GitHub documents that scheduled workflows can be delayed or dropped under load. The cause on GitHub's side is **UNVERIFIED**; the effect is verified.

## 4. Verified defects
| # | Severity | Defect | Evidence |
|---|---|---|---|
| D1 | P0 | CI red on every commit (F-08): rounding residue in stored probabilities | CI logs, runs 30–38; local reproduction on `3a1ead6` |
| D2 | P0 | Missed scheduled runs went unnoticed: no alerting. Failure e-mails go only to the last editor of the cron line, a no-reply commit author | run history above |
| D3 | P0 | After a failed restore, Export (`if: always()`) ran on an **empty** database and Publish force-pushed an empty dashboard that looked fresh | `autopilot.yml` (old) restore exits 1, then export/publish with `always()`; `cli.py` runs `init_db()` before `export-static` |
| D4 | P0 | `fil integrity` called `init_db()` first, re-creating missing triggers before checking for them, so removed triggers could never be detected | old `cli.py:55-63`, `db.py` `CREATE TRIGGER IF NOT EXISTS` |
| D5 | P0 | Settled-bet `payout`, `profit`, `settled_at`, `closing_price` and `clv` were mutable; dashboard ROI reads these columns | `IMMUTABLE["virtual_bets"]` lacked them; the resettle trigger fired only `OF status` |
| D6 | P1 | Unknown cron strings silently ran `results,fixtures_odds` (default `*)` branch) | old Pick-job step |
| D7 | P1 | The cron string and the manual `job` input were interpolated directly into shell code (`"${{ github.event.inputs.job }}"`), a script-injection pattern | old Pick-job / Run steps |
| D8 | P1 | Restore did not detect a database asset older than its manifest (e.g. the DB upload failed but the manifest upload succeeded); the guard compared only at persist time | old restore step |
| D9 | P1 | `fil.db.gz` and `manifest.json` were uploaded in one command; their order on failure was undefined | old persist step |
| D10 | P1 | Odds API errors were masked: `mark_success` ran unconditionally after `mark_error`, resetting the failure counter, so the circuit breaker could never open | old `collect.py:121-125` |
| D11 | P1 | A cancelled run could persist a `running` lease row, so every run for 90 min would be "skipped" while exiting 0 | `jobs.py` lease + `always()` persist |
| D12 | P1 | Live runs (39 a day) re-uploaded the 37.7 MB database and a 90-day artifact even when nothing changed | old persist and artifact steps |
| D13 | P1 | A partial job (a non-critical step failed) exited 0 with no annotation, so the workflow looked fully green | `cli.py` exits 1 only on `error` |
| D14 | P1 | The live phase was held for 3 h after the last snapshot, and the stored LIVE label was never re-evaluated in the browser (Pages serves snapshots up to 3 h old) | `api_b.py:82`; `InsightDetail.tsx` |
| D15 | P1 | The mobile CSS hid the "SIMULATION ONLY" notice (`.sim-banner { display: none }`) | `styles.css:83` |
| D16 | P2 | `|| true` around the run report hid its own errors | old Run report step |
| D17 | P2 | `restore()` overwrote the live DB before validating the backup | old `backup.py` |

## 5. Suspected risks (UNVERIFIED)
* GitHub may disable scheduled workflows after 60 days without repository activity. This is documented GitHub behaviour, but has not happened here yet.
* `gh release upload --clobber` deletes the old asset before the new one is complete. An upload killed mid-way could leave the release without `fil.db.gz`. The next run would then fail closed (no data loss, but an outage). Not observed.
* Anonymous GitHub API calls from the dashboard are limited to 60 per hour per visitor IP.

## 6. Safeguards that already worked (kept)
* Fail-closed download of `db-latest`.
* The shrink guard.
* Trigger-enforced immutability of predictions and ledgers.
* Step isolation with critical flags.
* Bounded provider retries with backoff and a stale-cache fallback (`providers/base.py`).
* Secret redaction (`security.py`).
* Provider keys scoped to the Run step.

## 7. Baseline tests
110 backend tests passed before this change on the then-current date. On 2026-11-23, one of them failed (D1).

## 8. Prioritised fixes (all implemented on branch `reliability/autopilot-hardening`)
D1 → D3 → D4 → D5 → D2 → D6/D7 → D8/D9 → D10 → D11 → D12/D13 → D14/D15 → D16/D17. See
[`AUTOPILOT_RUNBOOK.md`](AUTOPILOT_RUNBOOK.md) and [`RELIABILITY_STATUS.md`](RELIABILITY_STATUS.md).
