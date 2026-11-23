# Agent 6 — Live Football Systems Engineer

Reviewed commit `3a1ead6`, production DB snapshot `prod.db` (read-only), GitHub run history (REST), live dashboard headers. Checked 2026-11-23 01:47 UTC.

## 1. Current situation
"Live" today means **delayed score and status from football-data.org (free plan)**, pulled at most every 20 minutes by a GitHub Actions cron job and shown on a static GitHub Pages site. The production DB holds **0 rows in `eb_live_snapshots` and 0 in `eb_live_events`**. Because the free feed gives no minute, the code can never label a match LIVE or make a live prediction with the current configuration (`live.py:242`, `:299`). API-Football (minute, events, statistics) is coded and mock-tested, but `API_FOOTBALL_KEY` is not set. As of 01:47 UTC **no scheduled run has fired yet**: all 6 autopilot runs were `workflow_dispatch`. So the effect of real cron delays is UNKNOWN (not measured).

## 2. Evidence from the repository
| Topic | Evidence |
|---|---|
| Labels | `live.py:237-244`: LIVE needs a minute from the provider and data ≤180 s old. STALE means >1800 s old or more than 3.5 h after kickoff. Everything else is DELAYED |
| API-Football freshness | `live.py:175`: `provider_updated_at=now` (the time we fetched it), so "freshness" ignores how late the provider itself is. `now` is set once per poll (`:271`), so freshness can come out slightly negative |
| Live model | `live.py:213-234`: remaining-goal rate = pre-match rate × (94 − minute)/94, i.e. it assumes goals come at a constant rate. Red-card factors are 0.75/1.20 per card. Score state, game intensity and stoppage time are not modelled |
| Red-card detection | `live.py:292`: counts a red only if `"red" in detail`. A second-yellow dismissal whose detail text has no "red" would be missed. API-Football's exact wording is UNKNOWN; check it against a real fixture |
| Events | `live.py:166`: the event key includes minute, extra time, type, detail and player id. `:296` inserts with `on_conflict_do_nothing`. There is no delete or supersede path |
| Snapshot dedup | `live.py:305-311`: the hash covers status, 5-minute bucket, goals, reds, stats and label. It does **not** cover the provider. The unique constraint is `(fixture_id, input_hash)` (`db.py:417`) |
| Error isolation | `live.py:277-282` catches errors only around `live_matches()`. An exception in the per-match loop (`_link_fixture`, `pre.markets[...]`) rolls back the whole provider batch and fails the step |
| End of a match | fd.org is queried only with `status=IN_PLAY,PAUSED` (`live.py:77`), and API-Football only with `live=all`, so no final snapshot is ever written. `api_b.py:82-84` keeps phase=`live` for up to **3 h** after the last snapshot |
| Frontend | `common.tsx:15-18` and `InsightDetail.tsx:92` show the **stored** label. Nothing in the browser recomputes age. The only age banner is `main.tsx:31-33`, and it fires after **8 h** |
| Schedule | `autopilot.yml:19`: `*/20 11-23 * * *`. The last poll is at 23:40 UTC. The 3-hourly `40 */3` also includes `eb_live` (`jobs.py:37`) |
| Coverage gap | Since Jul 2025, kickoffs outside 11–22 UTC (real times, not 00:00 date placeholders): USA1 00–03 h ≈ 216 + 23 h 255; JPN1 312 of 312 (04–10 h); BRA1 23 h 113; MEX1 ≈ 476. These are polled once or never |
| Persistence | Every run, even a pure live poll, gunzips and checks a **148 MB** DB, then re-uploads `fil.db.gz` (**37,745,287 B**, `db-latest`, uploaded 2026-11-23 00:28) with `--clobber` (`autopilot.yml:101-121`). It also uploads a 90-day artifact (`:122-124`) |
| Run timing | Fastest run 45088776529 took 2.1 min: setup + pip + npm ≈ 33 s, restore 4 s, job 65 s (daily), persist 10 s, export 4 s, publish 2 s. A live-only run should take ≈ 60–80 s (estimate) |
| CDN | `curl -I …/data/insights.json` returned `cache-control: max-age=600` and `age: 72`, so Pages can serve data up to 10 min older than the last push |
| Doc inconsistency | `providers/others.py:183` license_note still says "Adapter not yet implemented" for API-Football, which contradicts `live.py:108-184` and `LIVE_DATA.md:12` |
| Tests | `test_engine_b.py:213-318`: 6 live tests pass (`pytest -k "live or apif"`, 6 passed). None covers a VAR reversal, an amended event, a second yellow, extra time or penalties, a per-match exception, quota exhaustion or label ageing |

## 3. What is working well
* The model is honest about what it lacks: when there is no minute, data is STALE, or the match is at half-time, no prediction is made (`live.py:299-300`, tested). Missing stats are never written as zero (`parse_apif_statistics`, tested).
* Each provider gets its own snapshot and providers are never merged. Pre-match predictions are never mutated (tested at `test_engine_b.py:261`).
* Snapshots are append-only, so a score correction shows up in the *latest* snapshot without rewriting history. Red cards are recounted from the provider's current event list on every poll, so a rescinded red is removed from the probabilities.
* Settlement never uses live data (`LIVE_DATA.md:19`).
* The concurrency group plus the fail-closed restore and shrink-guard is a sound way to serialise writes to one SQLite file.
* `LIVE_DATA.md:41-42` already says this is "near-live at best". That is the right framing.

## 4. What is weak or missing
1. **A static page can show "LIVE" for a long time.** A snapshot labelled LIVE at poll time keeps that badge on Pages until the next successful run. Data age when seen ≈ provider lag + schedule delay (UNKNOWN; GitHub warns that scheduled runs can be delayed under load, worst at the top of the hour: https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule) + ~1 min pipeline + Pages deploy + up to 10 min CDN + up to 20 min until the next poll. Typical age is roughly 15–35 min, and worse if a run is dropped. That breaks the rule "never call a delayed feed real-time".
2. **Finished matches look live** for up to 3 h, because the last snapshot of a match is never marked final.
3. **VAR and amended events are not handled in `eb_live_events`.** A disallowed goal stays in the table forever. An event whose player id or detail is later corrected becomes a second row with a new key. Nothing marks an event as "no longer reported by the provider".
4. **API-Football free quota will be exceeded.** 39 live runs + 8 three-hourly runs + 1 daily = 48 `/fixtures?live=all` calls a day, plus up to 3 statistics calls per run (up to 144 more). That totals up to 192 a day against the 100 a day stated in `live.py:109`. Whether the free plan serves the current season or live data at all is UNKNOWN: the pricing page could not be reached from this sandbox, so the owner must check it before relying on it.
5. **The statistical assumptions are rough and unvalidated.**
   * The constant-rate assumption ignores the well-documented rise in scoring rate late in matches (e.g. Dixon & Robinson 1998, *The Statistician* 47(3)).
   * 94 minutes understates modern stoppage time. A 45+3' first-half minute arrives as `elapsed=45` and the extra minutes are dropped.
   * There is no score-state effect: trailing teams push and leading teams sit back.
   * The 0.75/1.20 red-card factors are not calibrated on any data.
   * Extra time and penalties (`ET`, `BT`, `P` map to `live`) produce degenerate output: remaining time = 0.
   * There is no live calibration log (live log loss against the final result). Without that log, nobody can check whether the in-play probabilities are any good.
6. **Polling window.** It misses most of MLS, Liga MX, J-League and late Brazil and Argentina games. It also polls every 20 min when no covered match is in play.
7. **Persistence cost.** About 39 × 37.7 MB ≈ 1.5 GB a day of release uploads, plus 39 artifacts a day kept 90 days ≈ 130 GB (estimate). Each run also creates a new `actions/cache` entry (`key: provider-cache-${run_id}`). The repo is public, so this is free in money terms, but every `--clobber` upload is a chance to leave `db-latest` without `fil.db.gz`. That would make every later run fail closed (`:62`), and the risk grows with the number of uploads. A live poll with 0 snapshots still pays all of this.

## 5. Important risks
* **Integrity (P0):** users see a "LIVE 67'" badge that is 20–40 min old. Virtual "live" decisions made from it would be meaningless.
* **Availability:** 39+ full-DB rewrites a day multiply the chance of a corrupt or partial `db-latest`, which blocks the whole system (fail-closed is correct, but it hurts).
* **Silent loss:** one bad match aborts the whole live batch.
* **Quota:** with the key set, API-Football returns 429 by mid-afternoon. That error is handled (`live.py:139`), but live data stops for the rest of the day.
* **Cron reliability is unproven:** no scheduled run has fired yet.

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| LV-1 | Browser-side relabelling. Compute age = now − snapshot `at` in the browser. Show LIVE only if ≤3 min (impossible on Pages, so in practice never), DELAYED "x min ago" up to 30 min, then STALE. Show "Updated every ~20 min — not real-time" next to every live badge | MISSING | P0 | S | none | Playwright: a snapshot 25 min old renders "DELAYED · 25 min ago", never "LIVE"; the static build never shows the LIVE class |
| LV-2 | Live phase expiry and final marker: phase=`live` only if the last snapshot is ≤45 min old; when a tracked match drops out of the feed, write a terminal `left_feed` snapshot | MISSING | P0 | S | none | A test where a match is absent on the 2nd poll gives phase ≠ live; no "live" phase >45 min after the last snapshot |
| LV-3 | Live runs exit early and persist only on change. Run the live job only if `fixtures` has a covered kickoff in [now−150 min, now+5 min]. Upload `db-latest` and the artifact only if live rows were written. Skip the npm build for `job=live` | MISSING | P0 | S | none | Over 7 days, live runs with 0 snapshots upload 0 bytes; median live run <60 s |
| LV-4 | Isolate failures per match: wrap each match in a try/SAVEPOINT and log it, so the rest of the batch survives | MISSING | P1 | XS | none | Test: one match raising still stores the other match's snapshot |
| LV-5 | Event reconciliation: add `last_seen_at`, `status` (active/withdrawn), and a stable key (provider id + type + team + player, without detail or minute) plus an `amended` flag. Mark withdrawn when absent from a later full list. Detect second-yellow dismissals explicitly | MISSING | P1 | M | API-Football key to verify real payloads | Tests: a disallowed goal becomes `withdrawn`; an amended detail updates in place (1 row); a second yellow counts as a red |
| LV-6 | API-Football budget guard: fetch statistics only for covered in-play fixtures, cap at 90 calls a day using `x-ratelimit-requests-remaining`, and log calls per day | PARTIALLY IMPLEMENTED (`max_stat_calls=3`) | P1 | S | owner adds key; owner verifies the free-plan season/live terms | Calls per day ≤ 90 over 7 days; no 429 in logs |
| LV-7 | Shift the cron off the hour and widen it: `7,27,47 11-23` and `7,27,47 0-3` (Americas), gated by LV-3. Measure the schedule delay (`run_started_at − scheduled time`) in the run report | MISSING | P1 | XS | LV-3 | 14-day report shows the delay per run; MLS/BRA late kickoffs get ≥3 polls |
| LV-8 | Live model hygiene: time-varying rate (empirical goal-minute profile from history), stoppage-adjusted clock, freeze 1X2 at full time (no prediction in ET or penalties), keep the red factors labelled "approximate" until fitted. Add a live log-loss log per minute bucket against the final result | PARTIALLY IMPLEMENTED | P2 | M | ≥200 live-tracked matches (needs a minute-capable feed) | Live log loss at 15/45/75' is reported and beats the pre-match prediction at each bucket; no output during ET or penalties |
| LV-9 | Separate live state from the archive: the live poll writes a small `live.json` (and, at stage 3+, a tiny `live.db`) instead of rewriting the 148 MB DB; the 3-hourly job merges it into SQLite | MISSING | P2 | M | LV-3 | Live publish payload is <100 KB; `fil.db` is uploaded ≤10× a day |
| LV-10 | Fix the stale "Adapter not yet implemented" note (`providers/others.py:183`) and the README wording | MISSING | P3 | XS | none | grep finds no "not yet implemented" for API-Football |
| LV-11 | Add the provider to the snapshot hash (docs promise both providers' snapshots are kept) | MISSING | P3 | XS | none | Test: identical states from 2 providers produce 2 rows |
| LV-12 | Do not market Pages as live; no sub-minute polling on Actions; no paid feed or always-on host without owner approval | NOT RECOMMENDED (to change) | — | — | — | — |

### Staged architecture (what each stage needs)
| Stage | What the user gets | Infrastructure | Data provider | Free / low-cost option | Do NOT |
|---|---|---|---|---|---|
| 1 Delayed scores (today) | Score and status, typically 15–40 min old | GitHub Actions cron + Pages (as now, with LV-1/2/3) | football-data.org free (delayed) | Free | label it LIVE; persist the whole DB per poll |
| 2 Near-live (minutes) | Score + minute, 2–5 min old | A small scheduler outside Actions writing `live.json` to a CDN or KV store; SQLite archive stays on Actions | API-Football free or low tier (verify the terms) | Cloudflare Workers Cron Triggers + KV (free tier; check current limits at https://developers.cloudflare.com/workers/platform/limits/) or an Oracle Always Free VM | push to gh-pages every minute (Pages caps builds and caches 10 min) |
| 3 Live events | Goals, cards and subs with reconciliation (LV-5) | Same worker; events in D1 or a tiny SQLite on the VM, merged into the archive in batches | API-Football (events) | Worker + D1 free tier, or the VM | treat events as immutable; ignore VAR withdrawals |
| 4 Live statistics | Shots, corners, xG every 1–2 min | Always-on VM (Python poller + SQLite in WAL mode) + a small JSON API; ~1 call per covered match per minute | API-Football **paid** tier is very likely needed (quota) — **owner approval** | €0–5/month VM; paid feed only with written justification | invent missing stats; poll every fixture in the world |
| 5 Real-time (seconds) | Push updates in <10 s | Persistent server with WebSocket/SSE, a push feed from the provider, monitoring | Licensed push/websocket feed (commercial, typically costly) | None realistic for free | attempt it on Actions or Pages; call stages 1–4 "real-time" |

At every stage, SQLite stays the historical system of record; only the hot live state moves.

## 7. Top 3 recommendations
1. **LV-1 (browser-side relabelling).** This is the integrity issue. A static GitHub Pages site cannot be live: the CDN alone adds up to 10 minutes (measured `max-age=600`) and polls are 20+ minutes apart. A stored "LIVE" badge will mislead users the moment API-Football is turned on. Working out the age in the browser and capping the label at DELAYED/STALE is a small frontend change, and it enforces "never call a delayed feed real-time" whatever the backend writes.
2. **LV-3 (early exit and persist-on-change).** Most of the ~39 live runs a day will find nothing in play, yet each rewrites a 37.7 MB release asset and stores a 90-day artifact. Each of those uploads also risks a partial `db-latest`, which would block every job through the fail-closed restore. Gating the run on the fixture schedule and uploading only when rows changed removes most of that risk and cost. It costs nothing to set up, and it is a prerequisite for widening the window (LV-7).
3. **LV-2 + LV-5 (match lifecycle and event reconciliation).** Without a "match left the feed" marker, finished games stay "live" for up to 3 h. Without event withdrawal, a VAR-cancelled goal stays in the event log forever. Both must be fixed before stage 3 (live events) is worth turning on. The tests should be built from recorded real API-Football payloads once the owner adds the key.
