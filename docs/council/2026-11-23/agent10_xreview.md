# Agent 10 — Cross-review of Agent 9 (QA) and Agent 6 (Live)

## Agreements
- **LV-3 is the same as my OP-2** (gate live runs, persist only on change). This is the top shared finding. I accept its acceptance criteria: 0 bytes uploaded on live runs with no snapshots, median live run under 60 s.
- **QA-4 and LV risk 7 match my OP-5.** All three of us found the same non-atomic upload: the manifest was updated at 00:28:10 and `fil.db.gz` at 00:28:11.
- **QA-10 matches my OP-4** (open a GitHub issue on failure).
- **QA-15 matches my OP-6.** The `backup` health component is local to the runner and lost with it.
- **QA-9 matches my OP-7 and OP-10** (off-repo copy and restore drill).
- **QA-13 adds something I missed.** `GH_TOKEN` is set at job level (`autopilot.yml:39`), so the Run step executes unpinned PyPI code with `contents: write`. That token can delete `db-latest` and `db-backups`, which are the only copies. I agree with P2, and would raise it to P1 together with QA-9.

## Verified additions (I missed these)
- **QA-3 is confirmed, and I agree with P0.**
  - At `3a1ead6`, `cli.py:55-63` runs `init_db()` and `register_all()` for every command except `guard`/`restore`, which includes `export-static`.
  - If the restore step fails closed, Persist exits early (`[ -f data/fil.db ] || exit 0`).
  - But Export (`if: always()`) then builds a fresh, empty DB and force-pushes it to `gh-pages`. The fail-closed design therefore still publishes an empty dashboard.
  - I am adding this as **OP-13 (P0, XS)**: run export and publish only when `steps.restore.outcome == 'success'`.
- **QA-5 corrects an assumption of mine.** I had treated a 60-min timeout as killing the job before persistence. But `if: always()` steps also run on cancellation, so the `running` lease row can be persisted. The next runs are then `skipped` and exit 0 (`cli.py:76-78`), so nothing alerts. I agree with P1.

## Disagreements
1. **QA-4: "refuse when a manifest exists but is missing" conflicts with the documented recovery procedure.** `docs/OPERATIONS.md:63-65` restores production by *deleting* `manifest.json` as a deliberate override. Keep that override possible through an explicit `workflow_dispatch` input (for example `allow_manifest_reset=true`), not by deleting the file.
2. **QA-10's "daily dead-man check" workflow runs on the same scheduler it is meant to watch.** If schedules are auto-disabled after 60 days, or never fire (0 `event=schedule` runs as of 01:47 UTC), the watchdog is silent too. It is useful for "runs fail or stall". It is not a dead-man switch. That still needs either an owner check (OP-9) or an external pinger whose free tier nobody has verified.
3. **LV-7 (widen the window to 0-3 UTC): I disagree for now.**
   - With fd.org free there is no minute, so it adds about 12 runs a day of DELAYED scores.
   - With API-Football it makes LV-6's quota problem worse. LV's own estimate is up to 192 calls a day against 100.
   - The status should be "BLOCKED BY EXTERNAL DEPENDENCY". Only the off-hour shift (`7,27,47`) should go ahead now; it is part of my OP-3.
4. **LV-1 is P0 in wording only.** Today no snapshot can be labelled LIVE, because without a minute `live.py:242/299` never assigns it. The risk is latent. It should be P1, and a hard release gate before `API_FOOTBALL_KEY` is added.
5. **LV stage 2 (Cloudflare Workers + KV) cites limits that nobody verified** (both of us were blocked from developers.cloudflare.com). It would also need a second codebase (JS) that maps provider events to fixtures and predictions. Keep it NOT RECOMMENDED until the key exists and the owner approves.
6. **LV-9 (separate `live.json`) should be P3, not P2.** Once LV-3 is in place, the DB upload cost of live polling largely disappears.
7. **QA-9 effort.** An automated off-repo backup needs a credential for a second storage provider. Weekly owner download (OP-10) is XS and needs no new secret. Do that first.

## Changes to my recommendations
- **New OP-13, P0:** guard export and publish on a successful restore (adopts QA-3).
- **OP-5:** merge with QA-4. Add the sha256 to the manifest, upload the DB first, and offer an explicit reset input (see disagreement 1).
- **OP-4:** fold in QA-10's failure and stall issue. Its label stays "alerting", not "dead-man".
- **OP-3:** absorbs the minute shift from LV-7, but not the wider window.
- **New OP-14, P1:** scope `GH_TOKEN` to the persist and publish steps only (adopts QA-13 part), because the token protects the only backups.
- **OP-12 (VM): unchanged, NOT RECOMMENDED.** This is consistent with LV-12.
