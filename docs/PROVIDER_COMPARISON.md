# Live & historical football data — provider comparison

Research date: 2026-11-23. **Verified** means tested by us with real requests, or stated on the provider's official
page. **Reported** means it comes from third-party or marketing pages and still needs confirmation. **Unknown** means no
public information was found. No paid plan was purchased or activated.

| Provider | Coverage | Live data | Free access | Paid pricing | Licensing / integration | Our status |
|---|---|---|---|---|---|---|
| **football-data.co.uk** | 38 leagues, results since the 1990s, shots/corners/cards, xG (2026/27), opening and closing odds | none | free CSV (verified) | — | personal and non-commercial use with attribution; easy | **integrated (primary history)** |
| **football-data.org** | 12 competitions on the free tier (PL, ELC, PD, SA, BL1, FL1, DED, PPL, BSA, CL, EC, WC), seasons 2023+ | free tier: **delayed score and status only; no minute, events or statistics** (verified 2026-11-23: an "in-play" match was last updated 22 h earlier) | free key, 10 req/min (verified) | paid tiers add competitions, live data and odds; see football-data.org pricing | REST, simple | **integrated** (fixtures, results, standings, CL history, delayed live score) |
| **API-Football / API-Sports** | ~1,100 leagues and cups (reported) incl. CAF, Africa, Asia, Americas | live scores, minute, events, statistics, lineups, injuries | **100 requests/day, all endpoints** ([official pricing](https://www.api-football.com/pricing), [official guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)) | Pro 7,500/day, Ultra 75,000/day, Mega 150,000/day (official); ~$19–$39/month (reported by third parties, not confirmed) | commercial use allowed by plan terms; REST, simple | **adapter implemented and tested with mocks; awaiting `API_FOOTBALL_KEY`** |
| **Sportmonks** | 2,200+ leagues (official) | live scores, events, stats (paid) | free plan: **2 leagues only** (Danish Superliga, Scottish Premiership), 180 calls/hour/endpoint ([official free plan](https://www.sportmonks.com/football-api/free-plan)) | from €29/month (reported on Sportmonks' own comparison pages; [plans page](https://www.sportmonks.com/football-api/plans-pricing)) | REST; 14-day trial (needs a credit card) | not integrated (free plan too narrow) |
| **The Odds API** | ~70 sports, many soccer leagues, multiple bookmakers | live in-play odds on paid plans (reported) | free key, ~500 credits/month (reported) | paid tiers | REST | adapter ready (pre-match odds); **awaiting `ODDS_API_KEY`** |
| **Sportradar** | global, official league data deals | real-time, low latency | none public | enterprise contracts, not publicly priced | B2B licence | out of scope (no public pricing) |
| **Stats Perform / Opta** | global, event-level data, xG | real-time | none public | enterprise | B2B licence | out of scope |
| **Genius Sports** | official data rights (e.g. Premier League) | real-time | none public | enterprise | B2B licence | out of scope |
| **TheSportsDB** | community data, many leagues | v2 livescores on paid Patreon tier (reported) | test key `123`: ~1–15 events per call (verified) | Patreon | community licence | integrated for discovery only |

## What we know about SofaScore's data
SofaScore's corporate site says it works with "top-tier data providers" but does not name them
([about](https://corporate.sofascore.com/about)). The only publicly confirmed link is **Sportradar's involvement in
SofaScore's NHL tie-up** ([SportCal](https://www.sportcal.com/newsletters/nhl-agrees-multi-year-sofascore-tie-up/)). We make
**no claim** about SofaScore's football supplier, nor about the data suppliers of 1xBet or any other platform.

## Recommendation
1. **Now (free):** football-data.co.uk for history, statistics and odds; football-data.org for fixtures, results,
   standings and Champions League history. Both are integrated. Live mode is a **delayed score only**.
2. **Next (free, needs your action, after a quota guard exists):** register at API-Football and add the GitHub secret
   `API_FOOTBALL_KEY`. Only the **live** adapter exists (`fil/engine_b/live.py`, mock-tested, never run against the
   real API):
   * one `fixtures?live=all` request per poll (events included), plus statistics for at most 3 covered matches;
   * the current schedule (every 20 minutes, 11:00–23:40 UTC, 39 polls) can need **up to ~156 requests/day**, which is
     above the 100/day free limit. A request budget/quota guard is required first (council item DP-1);
   * it would add the live minute, events and statistics. It does **not** add lineups, injuries or African/Asian
     league fixtures: no adapter for those endpoints exists yet, and the free plan's season coverage is unverified.
   _Corrected 2026-11-23 by the AI Product Council review; the earlier text over-stated what the key unlocks._
3. **Later (paid, needs your approval):** API-Football Pro (7,500 requests/day) for frequent live polling and full
   global coverage. Alternatively, Sportmonks Starter for selected leagues.
4. Enterprise feeds (Sportradar, Stats Perform, Genius) need commercial contracts and are not practical for this project.

The architecture (`LiveProvider` interface in `fil/engine_b/live.py`) is provider-agnostic. Adding a provider means
implementing `live_matches()` and declaring its `capabilities`.
