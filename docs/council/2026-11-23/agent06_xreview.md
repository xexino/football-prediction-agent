# Agent 6 — Cross-review of Agent 5 (Providers) and Agent 10 (DevOps)

## Agreements
* **DP-1 (P0 quota guard)** matches my LV-6. Both reports count at least 48 requests a day from `poll()` running in three jobs, rising to 192 with statistics calls. DP-1 is broader because it also covers the Odds API, so it supersedes LV-6.
* **DP-3** (run the API-Football live adapter through `Provider.get`) complements LV-4 (per-match isolation). The live adapter has no circuit breaker and leaves no `DataSource` trace (`live.py:127-150`).
* **OP-2** (gated live runs with a pre-check on a small `kickoffs.json`) and **OP-8** (no artifact for live runs) are the same idea as LV-3.
* **OP-3** (staggered cron minutes) is the same as LV-7.
* **OP-12** (no VM now) is consistent with my staged table: a VM or worker only becomes worth having at stage 2 or later, with a minute-capable feed.
* **OP-5** (sha256 check after upload, database before manifest) is the right fix for the `--clobber` risk I raised.

## Disagreements and corrections
1. **DP-4's status is wrong.** It is listed as "IMPLEMENTED BUT NEEDS VERIFICATION", but `provider_updated_at=now` is still in the code at `live.py:175` (Agent 5 cites line 177). It should be **MISSING**.
   * DP-4 also fixes only the backend. On static Pages the stored LIVE label goes stale whatever the backend computes: the CDN adds up to 600 s (`max-age=600`, measured) and polls are 20 min apart. So **LV-1 (relabel in the browser) is still needed and stays P0**. DP-4 is a P1 companion to it.
2. **OP-2, "turn off the live cron until `API_FOOTBALL_KEY` exists": partly disagree.**
   * The football-data.org delayed score is the stage-1 product, and it feeds the `live` phase in `api_b.py:84`.
   * Gating on the fixture window (LV-3 / OP-2b) already removes most of the cost. Disabling the cron entirely is not needed.
   * I accept `*/30` only as a fallback if gating slips.
3. **OP-3's `queue: max`: UNKNOWN to me.** I could not verify that this concurrency option exists from public GitHub docs this session. Agent 10 cites docs-repo files.
   * A fix that does not depend on it: **drop the live cron at :40 of hours 12, 15, 18 and 21**. The three-hourly `fixtures_odds` job already runs `eb_live` (`jobs.py:37`), so those slots lose nothing.
4. **The OP-8 priority (P3) is too low for live runs.** Skipping the artifact on live runs belongs inside the P0 gating change (LV-3 / OP-2). Shorter retention for the other runs can stay P3.
5. **DP-8 (football-data.org "Livescores", about €12 a month, THIRD-PARTY CLAIM).** Whether this tier supplies the match `minute` is UNKNOWN.
   * If it does, it is the cheapest stage-2 option for the 12 competitions already integrated, and it should be added to my staged table, subject to owner approval.
   * If it does not, it is still DELAYED or near-live and must never be labelled LIVE.

## New points I accept and add to my own report
* **Pending-run cancellation (Agent 10 §4.2).** With one concurrency group, a queued three-hourly settle and predict run can be replaced by a live run. I missed this, and it makes the live cron a risk to Engine A as well, not just a cost.
* **`capabilities["lineups"]=True` with no lineups call (Agent 5, `live.py:116`).** The dashboard overstates what the provider gives (`Coverage.tsx:20`). I add this to LV-11: set the flag to False until lineups are actually fetched.
* **The API-Football free plan may only cover seasons 2022–2024** (Agent 5, from the vendor's blog). Live data for the current season on the free plan stays UNKNOWN until the DP-5 probe runs. **LV-5 and LV-8 now depend on DP-5.**
* **Provider update rate.** Agent 5 cites the vendor blog saying API-Football's `/fixtures` and events update about every 15 s. That supports stage 2 (minutes) on a worker. It does not make GitHub Actions viable below about 20 min.

## Revised items in my report
| ID | Change |
|---|---|
| LV-6 | Merged into DP-1. Status: MISSING (the `max_stat_calls` cap alone is not a guard) |
| LV-3 | Now also covers OP-8 for live runs. Stays P0 |
| LV-7 | Adds the :40 de-duplication described above. Raised from P1 to **P0**, because it protects settlement runs |
| LV-11 | Adds `lineups=False`. Stays P3 |
| LV-5, LV-8 | Now depend on DP-5 (probe the real payload and the season window first) |
| New pairing | DP-4 (P1) is paired with LV-1 (P0). Both are needed |
