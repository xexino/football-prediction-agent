# Agent 5 cross-review: agent06_live.md, agent11_growth.md

## Agreements
* **LV-6 = DP-1.** We each calculated the same API-Football budget independently: 48 `live=all` calls a day plus up to
  144 statistics calls, i.e. 48–192 a day against 100.
* **LV-1 / LV-2 match DP-4.** `provider_updated_at=now` (`live.py:175-177`) makes the LIVE label unreliable.
* **LV-10 = DP-2.** Same issue: the docs disagree about whether the API-Football adapter is implemented.
* **LV-12 and GR-8 match my "enterprise and sub-minute live out of scope".** FIL should not compete with
  SofaScore/FotMob on live scores.
* **GR-6 (coverage honesty map) fits DP-5/DP-6.** One condition: the "unlocking source" column must not name free
  API-Football until the probe confirms that the free plan serves the current season.

## Disagreements
1. **LV-6 does not cover The Odds API.** That is the larger quota risk. Credits cost markets × regions
   ([official v4 docs](https://the-odds-api.com/liveapi/guides/v4/)). The code requests 2 markets × 1 region × 16 sports
   (`others.py:114-148`) about 9 times a day. That is roughly 290 credits a day against 500 a month. On top of that,
   `mark_success` after `mark_error` (`collect.py:124-125`) hides the failures. **DP-1 should stay P0 and cover both
   keyed providers.** LV-6 at P1 is acceptable only for the API-Football half.
2. **LV-10 is rated P3, which is too low.** The doc errors (PROVIDER_COMPARISON.md:31-32) tell the owner that adding the
   key "stays within 100 requests/day" and "unlocks lineups and Africa". Both claims are false: no code calls
   lineups, injuries or pre-match fixtures. Acting on that advice triggers the quota failure described above. I keep
   **P1** and treat LV-10 as a duplicate of DP-2.
3. **LV-7 (widen polling to 0-3 UTC) is safe only after LV-3 gating.** Without the gate it adds 12 more baseline
   calls a day to an already exceeded budget. The LV-7 dependency should read "LV-3 **and** DP-1", not just LV-3.
4. **LV-6's acceptance criterion is incomplete.** "≤90 calls/day" also needs a **persisted** counter. Today
   `self.remaining` is read and then discarded (`live.py:138`). Each Actions run is a fresh process, so an in-memory
   cap does nothing.
5. **GR-2 lists ClubElo as a benchmark without noting that it is currently unusable.** DATA_SOURCES.md:51 says
   "host resets connections; unused". It should be marked BLOCKED BY EXTERNAL DEPENDENCY, or ClubElo should be dropped
   in favour of the market and naive baselines.
6. **Stage 2 in Agent 6's roadmap (Cloudflare Worker + KV) is premature.** It adds a second runtime and a new
   secrets location before DP-5 has shown that free API-Football serves live data at all. Its prerequisite should be
   DP-5 = pass.

## Wrong statuses
* **My own DP-4 status was wrong.** I marked it "IMPLEMENTED BUT NEEDS VERIFICATION"; it should be **MISSING**.
  Agent 6 is right that nothing measures provider-side freshness.
* **LV-11 (add the provider to the snapshot hash) is a correct finding.** The hash key in `live.py:304-305` omits the
  provider. Whether the unique constraint is on `input_hash` alone is UNKNOWN to me. If it is, LV-11 is P2, not P3,
  because the documented behaviour "both snapshots are kept" (LIVE_DATA.md:122) is broken.

## Changes to my recommendations
* **DP-1** absorbs LV-3's kickoff-window gate. Do not call `live=all` when no covered fixture is within
  [now−150 min, now+5 min]. That brings the zero-match baseline from 48 calls a day to about 0. The budget is persisted
  in `data_sources.quota_info`.
* **DP-4** is now MISSING and is paired with LV-1 (relabelling in the browser).
* **New DP-10 (P1, S): data-redistribution review**, prompted by the data-licence risk in Agent 11's §5.
  * The public `db-latest` release republishes 347,658 football-data.co.uk odds rows plus football-data.org data. GR-4
    would add full CSV/Parquet exports on top.
  * The redistribution terms of both sources are UNKNOWN to me. football-data.org requires attribution
    ([terms](https://api.football-data.org/register)).
  * Acceptance: the terms for each source are recorded in DATA_SOURCES.md, and GR-4 and the public DB release are
    gated on that review. Third-party rows are stripped or kept private if the terms forbid redistribution.
* **GR-3 (LICENSE)** must state that the code licence does not cover third-party data. I endorse it with that clause.
