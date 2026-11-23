# Agent 10 — DevOps and Autonomous Operations Architect

Reviewed commit `3a1ead6`. Evidence collected 2026-11-23 between 01:40 and 01:55 UTC. Note: `main` has since moved to `89211a4`, which adds `publish-discussion.yml`. That commit is outside the scope of this review.

## 1. Current situation
Production runs only on free GitHub-hosted runners (public repository). One workflow, `autopilot.yml`, has four crons, and all of them share the concurrency group `autopilot`. Each run does the same steps in order:
- checks out the code, installs pip and npm packages, and builds the frontend;
- downloads `fil.db.gz` (37.7 MB compressed, 148 MB raw) from the `db-latest` release;
- runs the job;
- guards the database, then re-uploads it to the release;
- stores a 90-day artifact;
- force-pushes the static dashboard to `gh-pages`.

**No scheduled run has executed yet.** `GET /actions/runs?event=schedule` returned `total_count: 0` at 01:47 UTC. All 41 runs so far were `workflow_dispatch`, `push` or `pull_request`. The `00:40` three-hourly slot was more than 67 minutes overdue. The workflow state is `active` and the default branch is `main`, so the cause is UNKNOWN: it could be a normal delay in registering a new schedule, or something else. Until a schedule fires, autonomy is unproven.

## 2. Evidence
| Item | Evidence |
|---|---|
| Schedules, concurrency, 60 min timeout | `.github/workflows/autopilot.yml:15-33` |
| Fail-closed restore, 4 retries | `autopilot.yml:53-72` |
| Guard, then upload with `--clobber`; daily copy to `db-backups` with 14 kept | `autopilot.yml:101-121`; `integrity.py:368-384`; `cli.py:47-53` (exits 1 on refusal) |
| 90-day artifact for every run | `autopilot.yml:122-124` |
| Steps marked critical or non-critical | `jobs.py:28-119`, `jobs.py:174-180` |
| Daily `backup` step writes to the runner's local `backup_dir`, which is thrown away with the runner | `jobs.py:57`; `backup.py:226-248` |
| Health thresholds | `health.py:101-104`; `docs/OPERATIONS.md:35-42` |
| Live poll produces in-play predictions only when the provider gives the minute | `engine_b/live.py:299-300` |
| Run durations (API, `workflow_dispatch` daily): 2.1, 2.3, 4.8, 8.0, 7.3 min; failed run 11.8 min | runs 45088776529, 45085048119, 45084090296, 45080092603, 45075952191, 45073611877 |
| Fixed overhead per run: about 30 s setup and install, 3-4 s restore, 10-15 s persist, about 10 s for artifact, export and publish. The daily "Run" step at steady state takes 65 s | jobs API step timings for 45088776529 |
| Release assets: `db-latest/fil.db.gz` 37.7 MB; `db-backups` has 2 assets of 37.6-37.7 MB each | `GET /releases` |
| `manifest.json` was updated at 00:28:10, `fil.db.gz` at 00:28:11 | `GET /releases`: the pair is not written atomically |
| 12 artifacts, 219.6 MB in total | `GET /actions/artifacts` |
| Database composition: `odds_observations` is 77.5 MB plus 39.7 MB of indexes (about 79% of the file); 347,658 rows | `dbstat` on `prod.db` |
| Health snapshot on Pages: `overall HEALTHY`, `computed_at 00:28Z`. It does not change after publishing | `/data/health_detail.json` |
| The cron lines were last changed by commit `22c7eaa`, authored by `Claude <noreply@anthropic.com>` | `git log -L19,19:.github/workflows/autopilot.yml` |

Official limits, read from the GitHub docs source (github/docs on raw.githubusercontent.com; docs.github.com is blocked from this session):
- **Public-repo standard runners are free:** `data/reusables/billing/compute-allowance-model.md`. Storage billing is described for private repositories: `content/billing/concepts/product-billing/github-actions.md:26-29`.
- **Only one pending run per concurrency group:** "any existing `pending` … will be canceled". The new `queue: max` setting allows up to 100 pending runs: `data/reusables/actions/actions-group-concurrency.md`; `content/actions/reference/limits.md:38`.
- **Schedule delays:** "delayed during periods of high loads … start of every hour … some queued jobs may be dropped": `data/reusables/actions/schedule-delay.md`.
- **Auto-disable:** "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days": `data/reusables/actions/scheduled-workflows-disabled.md`.
- **Failure notifications:** "Notifications for scheduled workflows are sent to the user who last modified the cron syntax": `events-that-trigger-workflows.md:1052`.
- **Releases:** up to 1000 assets per release, each under 2 GiB, "no limit on the total size of a release, nor bandwidth usage": `about-releases.md:47-49`.
- **Cache:** 10 GB per repository; entries unused for 7 days are evicted: `dependency-caching.md:359`.
- **Pages:** soft limits of 100 GB/month bandwidth and 10 builds/hour; site at most 1 GB: `github-pages-limits.md:23-27`.
- **Job time:** at most 6 hours per job: `limits.md:45`.

## 3. What is working well
- **Safety design is solid:**
  - Restore fails closed instead of falling back to an older snapshot.
  - Before upload, the guard checks integrity, the immutability triggers and the ledger chains, and refuses any database where an immutable table shrank.
  - A failed non-critical step never blocks persistence (`if: always()`).
  - Secrets are passed only to the Run step.
- **There are three copies:** `db-latest`, 14 daily backups, and 90-day artifacts.
- **Runs are short and cheap:** about 2 minutes at steady state, far below the 60 min timeout. Actions minutes cost USD 0 for a public repository.
- **The structured run report is useful.** It goes into `job_runs` and the step summary, records duration per step, and marks runs PARTIAL or FAILED.
- **Pages traffic is light.** At most about 4 dashboard pushes per hour, under the soft limit of 10 builds per hour.

## 4. What is weak or missing
1. **The live cron spends most of the schedule for almost nothing.** `*/20 11-23` means 39 runs a day, about 81% of all runs. Without `API_FOOTBALL_KEY`, the only configured live provider (football-data.org free) gives no minute, so `live.py:299` never produces a live prediction. Each live run still downloads and re-uploads 37.7 MB, writes a 36.6 MB artifact and republishes Pages.
2. **Scheduled runs can be silently cancelled.** With one shared group and the default single pending slot, a run waiting in the queue is cancelled when a newer run arrives. At 12:40, 15:40, 18:40 and 21:40 the three-hourly and live crons fire at the same minute. GitHub delays at the top of the hour can bunch runs together, so a three-hourly run (results, settle, predict) can be replaced by a live run. Cancelled runs do not send failure emails.
3. **No independent alerting.**
   - The only alert channel is GitHub's failure email, which goes to "the user who last modified the cron syntax". That was a commit authored as `noreply@anthropic.com`, so whether the owner receives anything is UNKNOWN.
   - If schedules are disabled, nothing fails, so nothing is sent.
   - The Pages health JSON is computed at publish time and freezes. Staleness shows only through the frontend's 8 h STALE banner, and only to someone who opens the page.
4. **60-day auto-disable.** It is UNKNOWN whether the bot's force-pushes to `gh-pages` count as "repository activity". A truly hands-off repository could stop itself after 60 days.
5. **Non-atomic persistence.**
   - `gh release upload --clobber` replaces assets in place, and `manifest.json` and `fil.db.gz` are uploaded separately.
   - Whether `--clobber` deletes the old asset before the new upload finishes is UNKNOWN; it depends on the gh version. If it does, a failed upload leaves `db-latest` with no database. The next run then fails closed, and the system stays down until someone restores it by hand from an artifact.
   - If the manifest is newer than the database, the guard can keep refusing to persist.
6. **The backup health signal is misleading.** The `backup` health component reflects the step that writes to the runner's own disk (`jobs.py:57`), which disappears with the runner. The real off-runner backup is the `db-backups` upload in YAML, and its success is never recorded.
7. **All copies share one failure domain.** The release, the backups and the artifacts all sit in the same GitHub repository and account. There is no off-GitHub copy and no restore drill.
8. **Redundant work on every run.** Each run reinstalls dependencies and rebuilds the frontend, about 30-40 s; the frontend is only needed for export. `actions/cache` saves a new key on every run (`provider-cache-${run_id}`). The cache size is UNKNOWN because the cache API is blocked by the proxy.

## 5. Important risks
| Risk | Likelihood | Impact |
|---|---|---|
| Schedules never fire or get disabled, and nobody notices | Medium (nothing fired yet) | Dashboard frozen; product stops |
| Three-hourly run cancelled by queued live runs | Medium in match hours | Settlement and predictions late by 3 h or more |
| Failure emails reach no one | UNKNOWN | Problems go unseen |
| `db-latest` left empty after a failed clobber upload | Low | Autopilot halted until manual restore |
| Loss of the GitHub account or repository | Very low | Total data loss (all copies are on GitHub) |

**Monthly volume at the current cron.** About 1,445 runs per month (live 1,170, three-hourly 240, daily 30, weekly 4). That is roughly 2,500 runner-minutes (estimate: live about 1.7 min, others 2-3 min, based on measured fixed overhead), plus CI. This is free on a public repository. It would exceed the 2,000-minute Free-plan allowance if the repository became private.

**Transfer and storage volume:**
- Release traffic: about 108 GB/month. Release bandwidth has no documented limit.
- Artifacts: about 53 GB/month, about 158 GB held at 90-day steady state. This is free for public repositories, but wasteful.

**Database growth.** Odds observations dominate, so the database grows by tens of MB per month. It stays far below the 2 GiB asset limit for years, but each run's transfer time grows in proportion.

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| OP-1 | Confirm that schedules fire: watch the first `event=schedule` runs for each cron; if none appear within 24 h, re-save the workflow (owner commit) or contact GitHub support | IMPLEMENTED BUT NEEDS VERIFICATION | P0 | XS | Owner | `GET /actions/runs?event=schedule` shows at least 1 daily, 6 three-hourly and 1 weekly run within 7 days; record delay p50 and p95 |
| OP-2 | Turn off the live cron (or limit it to `*/30`) until `API_FOOTBALL_KEY` exists. Add a cheap pre-check so live runs exit before restore and upload when no fixture kicks off within −150 to +15 min (for example from a small `kickoffs.json` published with the dashboard) | MISSING | P0 | S | none | Live runs per day 0 while unconfigured, or no more than the number of match windows; restore, persist and artifact steps skipped on no-match runs |
| OP-3 | Add `queue: max` to the concurrency block, and move cron minutes away from :00 and :40 collisions (for example live `7,27,47`, three-hourly `52`) | MISSING | P0 | XS | none | Over 14 days, 0 runs with conclusion `cancelled`; three-hourly runs all completed |
| OP-4 | Alerting that does not depend on a run failing: (a) on failure, or on guard refusal, a step opens or updates a GitHub issue labelled `autopilot-failure` (issue notifications go to the repo owner, not to the cron author); (b) the owner edits the cron line once personally, so schedule emails reach them; (c) an external dead-man switch if one is added later (healthchecks.io and similar: free tier NOT verified here, because the host was blocked) | MISSING | P1 | S | Owner for (b) | Forced test failure creates an issue within one run; the owner confirms an e-mail arrived |
| OP-5 | Make persistence safer: upload `fil.db.gz` before `manifest.json`; write a dated copy to `db-latest` first and clobber `fil.db.gz` last; after upload, re-download the asset and check that its size and sha256 match the file sent | PARTIALLY IMPLEMENTED | P1 | S | none | Persist step logs a matching sha256; a test with a simulated upload failure leaves a downloadable previous database |
| OP-6 | Record the `db-backups` upload result as the backup health signal (drop the runner-local backup, or relabel it "verify") | MISSING | P1 | XS | none | Health `backup` age reflects the newest `db-backups` asset timestamp |
| OP-7 | Weekly restore drill inside the `weekly` job: download the newest `db-backups` asset, run `fil integrity`, and compare its manifest with `db-latest` | MISSING | P1 | S | none | Weekly report shows `restore_drill: ok` with counts |
| OP-8 | Cut artifact retention to 7 days and stop the per-run artifact for live runs (backups already hold 14 days) | MISSING | P3 | XS | OP-2 | Artifact storage stays under 5 GB |
| OP-9 | Guard against the 60-day auto-disable: the dashboard shows the last scheduled-run time; the owner sets a monthly reminder to check the Actions tab. Avoid third-party "keepalive" actions that make dummy commits | MISSING | P2 | XS | Owner | Documented in OPERATIONS.md; schedules still active on day 61 |
| OP-10 | Off-GitHub copy: the owner downloads `db-backups` monthly to personal storage | MISSING | P2 | XS | Owner | Monthly copy exists and restores with `scripts/restore.sh` |
| OP-11 | Skip `npm ci && npm run build` when `frontend/` is unchanged (cache `frontend/dist` keyed on a hash of `frontend/**`) | MISSING | P3 | S | none | Median run time down by 10 s or more |
| OP-12 | Move to an always-on VM (for example Oracle Cloud Always Free, which lists "Arm-based Ampere A1 Compute" and "Block Volume", https://www.oracle.com/cloud/free/, but notes "Accounts left idle for 30 days or more may be deemed abandoned"). Exact quotas NOT verified (docs.oracle.com blocked). GCP, Cloudflare, Fly and Render free tiers were NOT verified (hosts blocked) | NOT RECOMMENDED now | P4 | L | Owner account | Revisit only if paid real-time live data (API-Football) needs polling more often than every 10 min |

**What NOT to add.** Do not add:
- Kubernetes, Docker registries, Terraform or multi-cloud;
- a hosted database (Postgres) or object storage: SQLite plus release assets fits the size and the write pattern;
- paid monitoring SaaS, or larger runners (billed even on public repositories);
- Cloudflare Workers for the Python, numpy or scipy pipeline. Its CPU limits are unverified and almost certainly unsuitable, and it would need a rewrite.

A VM brings back OS patching, disk management and an extra failure domain for a 2-minute batch job. Actions plus Pages is the better fit now.

## 7. Top 3 recommendations
1. **OP-2 plus OP-3: make the schedule fit the product.** About 81% of runs are live polls that cannot produce live predictions with the current provider (`live.py:299`). They also take part in the queue and can cancel the critical three-hourly settle and predict run, and every one moves 75 MB of database through releases. Gating live runs and adding `queue: max` with staggered minutes removes the main reliability risk and most of the bandwidth and artifact volume. It is about a 10-line change and costs nothing.

2. **OP-1 plus OP-4: prove the system runs on its own, and make sure a person hears when it does not.** No cron has fired yet, and failure emails go to whoever last edited the cron, which was a `noreply` commit identity. A system that runs without a human needs at least one alert channel that reaches the owner for sure. A GitHub issue opened on failure is free and lives in the same repository. It should be checked against the first week of scheduled runs.

3. **OP-5 plus OP-7: harden the one stateful operation.** The whole product state is a single 37.7 MB asset replaced about 48 times a day, with the manifest written separately. Writing in the right order, checking a checksum after upload, and a weekly automated restore drill turn the existing good guards (fail-closed restore, shrink guard) into a backup chain that has actually been tested. The cost is a few minutes of runner time per week.
