# Agent 5 — Football Data Provider and API Architect

Reviewed commit `3a1ead6` (verified with `git rev-parse HEAD`). Production DB snapshot opened read-only.
**Research limitation:** this session's network allowlist blocked direct fetches of the provider sites (football-data.org,
api-football.com, the-odds-api.com returned DNS failure). External facts below come from web-search snippets of
official pages. Each one is labelled **OFFICIAL** (snippet of the vendor's own page or docs), **THIRD-PARTY CLAIM**, or **UNKNOWN**.
They must be re-checked on the vendor pages before any purchase.

## 1. Current situation
* Four providers are working in production: football-data.co.uk, TheSportsDB, martj42 international results and football-data.org.
  `data_sources` shows all four `ok` with last success at 2026-11-23 00:27.
* Two providers are registered but `not_configured`: The Odds API and API-Football. All 347,658 `odds_observations` come
  from football_data_uk.
* `eb_live_snapshots` = 0 and `eb_live_events` = 0. Live mode has never stored a real snapshot.
* Fixtures by first source: fd_uk 47,608, intl 8,393, fdorg 2,630, TSDB 140.
* Africa is token coverage only. CAFCL 17 fixtures, EGY1 17, MAR1 16, RSA1 17, TUN1 17, CAFCC 1, and ALG1/NGA1 0.
  LIB, KSA1 and KOR1 also have 0. USA1 (2,589) and JPN1 (1,526) are well covered via football-data.co.uk.

## 2. Evidence from the repository
| Item | Evidence |
|---|---|
| Shared HTTP base: cache, stale-cache fallback, 429 back-off, 3-failure circuit breaker (6 h), quota_info | `providers/base.py:19-20, 83-109, 122-169` |
| football-data.org: 6.2 s spacing, header-driven throttle, 400→AuthError, 403→Restricted | `providers/football_data_org.py:36-53, 81-146` |
| API-Football **pre-match** adapter is a placeholder: "Adapter not yet implemented" | `providers/others.py:174-187` (line 182) |
| API-Football **live** adapter implemented: `fixtures?live=all` + ≤3 `fixtures/statistics` | `engine_b/live.py:108-184` |
| Live adapter bypasses `Provider`: raw `httpx`, no cache, no retry, no circuit breaker, no `DataSource` quota write; `self.remaining` is read and then discarded | `live.py:127-150` |
| `capabilities["lineups"]=True` but no lineups endpoint is ever called | `live.py:116` |
| `provider_updated_at=now` for API-Football, so freshness is always ≈0 s and the LIVE label can never detect provider-side staleness | `live.py:177` |
| `APIF_IDS` "to be re-checked once key is set"; `WCQ→1` (World Cup finals) and `UNL→5` (Nations League) although the catalogue groups qualifiers and the Euro into those codes | `catalog.py:93-106, 63-68` |
| Odds API: `regions=eu`, `markets=h2h,totals` for 16 sports per run; a failure is logged, then `mark_success` overwrites it | `others.py:114-171`, `collect.py:113-126` |
| `collect_fixtures` runs in `fixtures` (every 3 h) and `daily`; `eb_live` runs in `live` (*/20 11-23), `fixtures` and `daily` | `jobs.py:35-54,116`; `autopilot.yml:16-19` |
| Provider cache is persisted across Actions runs (`actions/cache`, `data/cache`) | `autopilot.yml:46-50` |
| Tests: API-Football live parsing, normalisation and missing-key error pass (6 passed, `-k "apif or live"`); **no test for `OddsAPI`** | `tests/test_engine_b.py:281-310` |

### Doc ↔ code inconsistencies
1. **README.md:77** says "`API_FOOTBALL_KEY` Reserved; the adapter is not implemented yet". **DATA_SOURCES.md:50** says
   "adapter not implemented". `others.py:182` says the same. Against these, **PROVIDER_COMPARISON.md:11, 28-31** and
   **LIVE_DATA.md:116** say "adapter implemented and tested with mocks". The truth is in between: *live* is implemented and
   mock-tested; *fixtures, injuries, lineups and history* are not.
2. **PROVIDER_COMPARISON.md:31** says a key "unlocks … lineups and the African and Asian leagues". This is wrong. No code
   fetches API-Football fixtures, lineups, injuries or results. African fixtures would only appear as side effects of live
   polling (`_link_fixture`, `live.py:247-265`).
3. **PROVIDER_COMPARISON.md:32** says a 20-minute poll "stays within 100 requests/day". The schedule gives 39 live runs
   (13 h × 3), plus 8 `fixtures` runs and 1 `daily` run, each calling `poll()`. That is ≥48 requests/day with no live
   match, and up to 192 with 3 statistics calls each. The free cap is exceeded on any busy match day.
4. **PROVIDER_COMPARISON.md:13** labels The Odds API's 500 credits as "reported". The vendor's own pricing and docs state
   it (**OFFICIAL**, below).
5. "38 leagues" for football-data.co.uk (PROVIDER_COMPARISON.md:9): the catalogue maps 22 main and 15 extra = 37. Minor.

## 3. What is working well
* Provenance is excellent: per-source `odds_observations`, `result_observations`, `external_ids` and content hashes
  (DATA_SOURCES.md:55-58).
* The rule that sources are never merged into one live snapshot, and the rule that settlement only comes from verified
  results (LIVE_DATA.md:119-123), are the right design.
* `LiveProvider` + `capabilities` is a clean, provider-agnostic seam. Missing stats stay missing (`live.py:195`, tested).
* football-data.org handling is careful and was verified against the real API (header throttle, 403 → restricted list).
* The free-first stack already gives 37 leagues of history, odds, shots, corners and xG (2026/27) at zero cost.
  Do not rebuild it.

## 4. What is weak or missing
* **There are no quota guards** for the two keyed providers waiting for a key. Enabling `ODDS_API_KEY` today would cost
  2 credits (2 markets × 1 region) × 16 sports = 32 credits per run. That is about 9 runs/day (3-hour TTL ≈ 3-hour
  schedule, so few cache hits), or ~290 credits/day against **500/month**. The quota would be gone in about 2 days.
  API-Football would hit 100/day on busy days.
* The live adapter duplicates HTTP logic outside `Provider`. It has no circuit breaker and leaves no `DataSource` trace.
  A dead key would fail silently every 20 minutes.
* There is no pre-match API-Football adapter (fixtures, results, lineups, injuries) and no league-coverage check.
  API-Football's `/leagues` response includes per-season `coverage` flags (from v3 docs; **not re-verified this session**).
  These flags should drive capability per competition instead of the hard-coded `True`.
* There are no provider-quality metrics: score disagreement rate, result-latency, unresolved-team rate per source.
* No open event-level/xG history beyond football-data.co.uk 2026/27 xG.

## 5. Important risks
* **Quota exhaustion on day 1 of adding keys** (see §4). Errors are masked by `mark_success` after `mark_error`
  (`collect.py:124-125`).
* **False "LIVE" label**: freshness is computed from retrieval time, not provider time, for API-Football.
* **Free-plan season window**: API-Football's own blog says the free plan covers only seasons Year-4…Year-2
  (currently 2022–2024) (**OFFICIAL-blog**, [api-football.com league guide](https://www.api-football.com/news/post/how-to-get-all-data-from-a-league-with-api-football)).
  If correct, the free key gives *live* data (fixtures `live=all` is current) but **not current-season pre-match
  fixtures or history**. Verify with a real key before building on it.
* **Licensing**: football-data.org requires attribution
  ([terms](https://api.football-data.org/register)). StatsBomb open data is under a custom user agreement (not a standard open
  licence) with attribution required ([github.com/statsbomb/open-data](https://github.com/statsbomb/open-data)).
  Understat: terms **UNKNOWN**, so do not scrape it.
* Wrong `APIF_IDS` would silently drop or misfile matches (`comp_code=None` is skipped).

## External research summary
| Provider | Free | Paid | Live | Label |
|---|---|---|---|---|
| football-data.org | 12 comps, 10 req/min, delayed scores (also verified by us) | Livescores ~€12/mo (20/min); Standard €49 (60/min, ~25–30 comps); Advanced €99 (50 comps); Pro €199 (100 comps); odds/stats add-ons ~€15 | live scores from €12 tier | THIRD-PARTY CLAIM (official page not reachable) |
| API-Football | 100 req/day, all endpoints, no card ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide), [pricing](https://www.api-football.com/pricing)) | Pro 7,500/day etc. (official); USD prices UNKNOWN here | `/fixtures` & events updated every 15 s ([WC 2026 guide](https://www.api-football.com/news/post/fifa-world-cup-2026-guide-to-using-data-with-api-sports)) | OFFICIAL (vendor blog); per-minute limit (10 vs 30) UNKNOWN |
| The Odds API | 500 credits/month; cost = markets × regions; `/sports` free; headers `x-requests-remaining/used/last` ([v4 docs](https://the-odds-api.com/liveapi/guides/v4/)) | tiers UNKNOWN | in-play odds UNKNOWN | OFFICIAL |
| Sportmonks | 2 leagues (Danish Superliga, Scottish Prem), both already covered by fd_uk | Starter €29, Growth €99, Pro €249/mo; league counts 5/30/120 vs "any leagues" conflict ([plans](https://www.sportmonks.com/football-api/plans-pricing), [blog](https://www.sportmonks.com/blogs/introducing-our-new-pricing-setup/)) | yes (paid) | OFFICIAL (prices); league counts conflicting |
| Sportradar | 30-day trial; production for customers only ([dev portal](https://developer.sportradar.com/getting-started/docs/your-account)) | not public | yes | OFFICIAL |
| Genius Sports | none | enterprise | official FDC/Premier League betting data supplier ([Genius newsroom](https://geniussports.com/newsroom/premier-league-productions-partners-with-genius-to-deliver-ground-breaking-premier-league-data-zone/)) | OFFICIAL/press |
| Stats Perform/Opta | none public | enterprise | yes | UNKNOWN pricing |
| openfootball | public domain, no key ([football.json](https://github.com/openfootball/football.json)) | — | none | OFFICIAL (repo README) |
| StatsBomb open data | free, non-commercial user agreement, selected competitions, event data + xG | — | none | OFFICIAL (repo) |

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| DP-1 | **Quota guard per keyed provider.** Daily/monthly budget in `quota_info`; read `x-requests-remaining` / `x-ratelimit-requests-remaining`; skip calls below a reserve. Odds API: limit to ≤4 priority sports, once per day, h2h only, unless budget allows. | MISSING | P0 | S | none | Simulated 30-day schedule uses ≤450 Odds credits and ≤90 API-Football req/day; unit test with mocked headers stops calls at the reserve |
| DP-2 | Fix README:77, DATA_SOURCES:50, `others.py:182` and PROVIDER_COMPARISON:31-32 to state "live adapter implemented (mock-tested); pre-match adapter not implemented; request budget is 48–192/day". | PARTIALLY IMPLEMENTED | P1 | XS | DP-1 for numbers | All 4 places agree; doc check in CI greps for "not implemented" contradictions |
| DP-3 | Move `APIFootballLive._get` onto `Provider.get` (circuit breaker, `DataSource` status/quota, redaction). Fix `mark_error`→`mark_success` masking in Odds collection. | MISSING | P1 | S | none | A dead key shows `error` + open circuit on the Data Sources page after 3 runs; test for both |
| DP-4 | Honest freshness: drop `provider_updated_at=now`; use provider data only, and label API-Football as LIVE only when the `elapsed` changed between polls or the poll is ≤3 min old *and* the status is in-play. | IMPLEMENTED BUT NEEDS VERIFICATION | P1 | XS | none | Test: an unchanged `elapsed` across 2 polls ≥10 min apart → DELAYED |
| DP-5 | Owner adds the free `API_FOOTBALL_KEY` and `ODDS_API_KEY`. First run is a one-off probe: `/status`, `/leagues?id=` for every `APIF_IDS` entry (≈60 req, so spread over 1 day), recording `coverage` flags and the season window. Fix WCQ/UNL/AFCON qualifier ids. | BLOCKED BY EXTERNAL DEPENDENCY | P1 | S | owner, DP-1 | Probe report stored; every APIF id resolves to the expected name; `capabilities` per competition comes from coverage flags |
| DP-6 | Pre-match API-Football adapter (fixtures/results for Africa, Libertadores, KSA, KOR), **only if** DP-5 shows the free plan serves the current season. Otherwise document as paid-only. | MISSING | P2 | M | DP-5 | CAFCL/EGY1/MAR1 each ≥30 current-season fixtures with results, or a documented "paid-only" decision |
| DP-7 | Provider-quality monitor in `health.py`: per source, the score disagreement rate vs football-data.co.uk, result latency (kickoff→first result), unresolved-team rate, and quota remaining. | MISSING | P2 | S | none | `health_detail.json` exposes 4 metrics per source; alert on a disagreement rate >1% |
| DP-8 | Paid upgrade path (owner approval): football-data.org "Livescores" (~€12/mo, THIRD-PARTY CLAIM) is the cheapest real live score for 12 comps already integrated. API-Football Pro covers Africa and lineups. Buy only after 4 weeks of DP-7 data show live/Africa usage. | NOT RECOMMENDED yet | P3 | XS | owner, DP-7 | A written decision with confirmed official price and usage evidence |
| DP-9 | StatsBomb open data for offline xG/feature research (non-commercial, attribution); openfootball as a public-domain fixture cross-check. No scraping of Understat or SofaScore. | MISSING | P4 | M | licence review | Licence text stored in docs; data used only in research notebooks or tests |

## 7. Top 3
1. **DP-1 Quota guards.** This is the only change needed before the owner adds the two pending keys. Without it, the
   current schedule burns The Odds API's 500 monthly credits in ~2 days, because 16 sports × 2 markets are fetched ~9×/day.
   It also exceeds API-Football's 100/day on busy days, because `poll()` runs in three jobs. Both failures would be
   partly hidden by the success-overwrite bug. This is a cheap, deterministic fix that protects the free-first strategy.
2. **DP-3 + DP-4 Live adapter hardening.** Live mode has produced 0 snapshots so far. When it starts, the
   API-Football path has no circuit breaker or status trace, and it labels everything LIVE because freshness is measured from
   our own retrieval time. Routing it through the existing `Provider` base reuses tested code and keeps the honest-label
   promise in LIVE_DATA.md.
3. **DP-5 Verify-before-build probe, then DP-2 docs.** The vendor's own blog suggests the free API-Football plan may not
   include current-season pre-match data. The Africa/Libertadores plan in PROVIDER_COMPARISON.md therefore rests on an
   unverified assumption. A one-day, ~60-request probe settles the season window, the coverage flags and the `APIF_IDS`
   correctness. The docs can then state one consistent truth instead of the current three.
