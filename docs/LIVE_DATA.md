# Live data

## Architecture
* `fil/engine_b/live.py` normalises every provider into a `LiveMatch`:
  * provider and provider event ID; competition; teams; kickoff;
  * status; minute and its source (provider, estimated or unknown); score;
  * statistics (**only fields the provider supplied**); events; provider update time; retrieval time.
* Providers implement `LiveProvider.live_matches()` and declare `capabilities`.

| Priority | Provider | Fields | Status |
|---|---|---|---|
| 1 | API-Football | score, minute, status, events (goals, cards, subs), statistics (corners, shots, shots on target, possession, fouls, offsides, cards, xG when supplied) | awaiting `API_FOOTBALL_KEY` (mock-tested) |
| 2 | football-data.org | score and status only (free plan, **delayed**) | active |

## Source-priority policy
* Each snapshot names exactly **one** provider; data from different providers is never merged into one record.
* The dashboard shows the highest-priority provider's latest snapshot.
* If providers disagree on a score, both snapshots are kept and nothing is overwritten.
* Final results for settlement still come from the verified-results pipeline, never from live snapshots.

## Labels
| Label | Meaning | Live prediction? |
|---|---|---|
| LIVE | provider gives the match minute and the data is ≤ 3 minutes old | yes |
| DELAYED | score without a reliable minute, or 3–30 minutes old | no |
| STALE | more than 30 minutes since the provider update, or more than 3.5 h after kickoff | no |

## Live prediction
* The **remaining** goals for each team are Poisson with mean = Engine B pre-match rate × remaining share of 94 minutes.
* A red card multiplies the short-handed team's rate by 0.75 and the opponent's by 1.20. These factors are approximate
  and stated in every snapshot.
* Outputs: 1X2, Over/Under 0.5–4.5, BTTS, next goal.
* Snapshots (`eb_live_snapshots`) are written only when the score, status, 5-minute bucket, red cards or statistics
  change; a unique input hash prevents duplicates.
* Events (`eb_live_events`) are de-duplicated by provider event key.
* **Pre-match predictions are never modified** (tested).

## Polling
* The `live` autopilot job runs every 20 minutes from 11:00 to 23:59 UTC. Each run makes 1 football-data.org request, plus
  1 + ≤ 3 API-Football requests when that key is set.
* GitHub Actions schedules can start several minutes late, so this is near-live at best. True live (seconds) would need
  an always-on server and a paid feed.

## Verified so far
* **2026-11-22 23:57 UTC:** a real football-data.org request returned one "IN_PLAY" match (Chapecoense–Cruzeiro, Brasileirão).
  It had score 0–0, `minute` null, and was last updated 22 h earlier. This is the behaviour that motivates the STALE label.
* **2026-11-23 ~00:30 UTC:** a real poll returned 0 in-play matches. Live snapshots from real matches will appear once
  scheduled polls run during match hours.
