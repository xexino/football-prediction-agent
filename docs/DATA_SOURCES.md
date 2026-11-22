# Data sources

All sources are used within their published access terms. No paywall, authentication or rate limit is bypassed.

| Provider | Access | Data used | Refresh | Reliability | Status |
|---|---|---|---|---|---|
| football-data.co.uk | free CSV, no key | results, HT scores, shots, SoT, corners, fouls, cards, **xG (2026/27)**, pre-match + closing odds (Bet365, Pinnacle\*, bwin, Betfair Exchange, market avg/max) for 1X2, O/U 2.5, Asian handicap; weekly fixtures with odds | ~2×/week | high | **primary, active** |
| TheSportsDB (`123` key) | free public test key | fixture discovery and result cross-checks: UEFA cups, CAF, Egypt, Morocco, South Africa, Tunisia, top-5 leagues | on demand | medium | active, very limited (1 next + 1 past event per league); circuit breaker |
| martj42/international_results | GitHub CSV, CC0 | national-team results since 2016 (Elo, coverage) | irregular | high | active |
| football-data.org | free API token (`FOOTBALL_DATA_ORG_KEY`) | fixtures, results (90-minute score; extra time flagged), standings, for PL, ELC, PD, SA, BL1, FL1, DED, PPL, BSA, **CL**, EC, WC; seasons 2023–2026; Champions League history backfilled | quick sync every 3h (1 request), full sync daily (~25 requests), 10 req/min | high | **active once the secret is set** (verified with a real token 2026-11-22) |
| The Odds API | free key | more bookmakers, UEFA odds (h2h, totals) | 500 credits/month | high | adapter ready, **key missing** |
| API-Football | free key | injuries, lineups, African leagues, live scores | 100 req/day | high | registered, **adapter not implemented**, key missing |
| ClubElo | — | — | — | — | host resets connections; unused |

\* Pinnacle columns are present in older seasons only.

## Provenance
Every stored item carries its source and retrieval time: `odds_observations` (source, bookmaker, kind, retrieved_at,
source_url, content hash), `result_observations` (per source), `match_stats` (source, retrieved_at), `fixtures.first_seen_source`
and `external_ids`. Network failures fall back to cached copies, which are labelled with the cache time.

## Identity resolution
Fixtures are matched on competition + home/away team + kickoff within ±36 h. Team names are resolved through exact
aliases, then normalised aliases, then fuzzy matching within the competition, then **anchor matching** (one team and the
kickoff identify the fixture, so the other name becomes an alias). A merge pass folds earlier duplicates.

## Validation on import
Rejected and counted, never repaired by guessing:
* scores outside 0–20;
* results for matches that have not started;
* half-time scores above full-time;
* identical or missing team names;
* kickoff dates before 1990 or more than 400 days ahead;
* unparseable rows, HTML instead of CSV, malformed JSON.

## African & under-covered competitions
| Competition | Fixtures | History | Odds | Eligible | Blocker |
|---|---|---|---|---|---|
| CAF Champions League / Confederation Cup | TheSportsDB (1–2 events) | none usable | none | no | API-Football key |
| Egypt, Morocco, South Africa, Tunisia leagues | TheSportsDB (1–2 events) | none usable | none | no | API-Football key |
| AFCON + qualifiers | none upcoming | martj42 results | none | no | fixtures + odds source |
These appear on the dashboard as **DATA COVERAGE ONLY — PREDICTIONS NOT ENABLED**.

## football-data.org: what the free plan (TIER_ONE) allows
Verified with real requests on 2026-11-22.

| Endpoint / data | Free plan |
|---|---|
| `/competitions` | ✅ 12 competitions (plan TIER_ONE) |
| `/competitions/{c}/matches` (fixtures + results) | ✅ seasons 2023, 2024, 2025, 2026 · ❌ 2022 and earlier (HTTP 403) |
| `/matches?dateFrom&dateTo` (window ≤ 10 days) | ✅ |
| `/competitions/{c}/standings` | ✅ overall table (`TOTAL`) |
| `/competitions/{c}/scorers`, `/teams` | ✅ (not stored yet) |
| Odds | ❌ paid "Odds-Package" |
| Lineups, match statistics, live data | ❌ not on this plan. Scores of matches in play are **delayed** and are never stored or shown as live |
| Other competitions (e.g. AFCON qualifiers) | ❌ HTTP 403 |

* **Rate limiting:** at most one request every 6.2 s. Before each request the client reads `X-Requests-Available-Minute`
  and `X-RequestCounter-Reset`; when one request is left it waits for the counter reset. HTTP 429 waits for
  `Retry-After` / `X-RequestCounter-Reset` (capped at 65 s) and retries up to 4 times.
* **Failure handling:** an invalid token returns HTTP **400** ("Your API token is invalid") and is reported as a
  configuration error with no retry. HTTP 403 means "not in your plan" and is recorded in the provider's
  `restricted` list.
* **Duplicates:** fixtures are linked by football-data.org match id once matched. In leagues owned by football-data.co.uk,
  a team name that cannot be matched is skipped (counted as `unresolved_teams`), never invented. Standings are stored as
  one snapshot per team per day.
