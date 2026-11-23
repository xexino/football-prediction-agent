# Agent 4 — Football Intelligence and Match Analysis Specialist

## 1. Current situation
The "AI Match Analyst" is a deterministic template (`backend/fil/engine_b/insights.py`, 108 lines, no LLM) that produces per-fixture `sections` (assessment, goals, corners, cards, form, H2H, confidence) and lists of supporting, contradicting and missing factors. Engine A has a parallel explainer (`backend/fil/explain.py`) that is stored in `predictions.inputs['explanation']` (93 of 121 rows). Both are honest about missing data, and neither invents injuries or lineups. But the output repeats itself, the confidence labels are inflated, and the analysis skips half of the matchup. It also ignores data we already hold: xG, shots, HT scores and standings. The prod snapshot has 130 `eb_predictions`, 0 `eb_evaluations`, 0 `eb_live_snapshots`/`eb_live_events`, 0 `players`, 0 `team_news`.

## 2. Evidence from the repository
**Code**
- Favourite strength label: `insights.py:30`. The label is "clear" when the 1st–2nd gap is > 20 pp, whatever the absolute probability.
- Supporting/contradicting factors: `insights.py:56-60`. They use only home attack (`h_goals_att`) and away defence (`a_goals_def`). Away attack and home defence are never considered. The routing `(x>=0)==(fav=="home")` treats a draw favourite as an away favourite.
- Confidence label: `insights.py:103`. The label is "high" at ≥70, with no link to validated accuracy.
- Corners caveat hard-coded with fixed numbers ("2.73 vs 2.72 on 4,779 matches"): `insights.py:43`. Meanwhile `eb_validation_runs` = 0 rows in prod, and the brief cites 4,845 matches.
- Team EWMA state and `n` are cross-competition, with no league-strength adjustment: `features.py:105-128`. For promoted Frosinone, `n_home`=126 includes 76 Serie B matches (query below).
- xG is loaded (`features.py:48`, `h_xg`) but is not in `METRICS` (`features.py:26`). It is never shown or used.
- Live in-play model: `live.py:213-235`. This is a remaining-time Poisson model with approximate red-card factors, plus a next-goal output. No momentum is computed anywhere.
- UI: `InsightDetail.tsx:72` renders sections as a flat list of paragraphs. `:81` has a correct-score matrix, and `:89-101` holds the live card. `Upcoming.tsx:51-60` shows the form strings, table and team-news status, and `:75` shows the Engine A explanation.

**DB queries (read-only, prod snapshot)**
| Metric over 130 Engine B reports | Value |
|---|---|
| Confidence label "high" / moderate / low | 102 / 19 / 9 |
| "high" while data_quality < 70 | 17 |
| "clear favourite" with favourite < 50% | 16 |
| Top correct score = 1-1 | 112 (86%) |
| Main uncertainty is a < 10% effect | 30 |
| "Confirmed lineups…" missing line | 130/130 (always) |

| Data we hold | Coverage |
|---|---|
| `match_stats` shots, SOT, corners, fouls, cards (football-data.co.uk) | 23,914 matches, 18 European leagues, 2023– |
| `match_stats.home_xg` | 2,033 matches, current 2026/27 season only, 18 leagues |
| HT scores (`fixtures.ht_home_goals`) | 26,698 finished fixtures |
| Standings | 212 rows (ITA1 etc. via football-data.org; none for ARG1) |
| Odds observations | 347,658 |
| Players, team news, live snapshots and events | 0 |

`data_sources`: `api_football` and `the_odds_api` are `not_configured`.

**Example 1 (eb_predictions.id=1, Instituto–Huracán, ARG1).** Report text: "Engine B makes Instituto the **clear** favourite (Instituto 47% · draw 27% · Huracan 26%)… most likely scores 1-1 (13%)…". Confidence: "Confidence is **high (75/100)** with data quality 65/100. Main uncertainty: **Huracan concede 2% less than average**."
- The quality breakdown shows shot/corner stats = 0, league table = 0 and team news = 0.
- Critique: a 47% favourite is not "clear", and the headline also says the most likely score is a draw, with no explanation of how both can hold. The "main uncertainty" is a 2% effect, which is noise.
- The report omits a real supporting factor: Huracán's attack is −25% (`a_goals_att`=−0.289), because away attack is never checked.
- "rest 15 vs 15" is fine, but "1 wins, 1 draws" is a grammar slip. "High" confidence is shown with no shot data and no table.

**Example 2 (eb_predictions.id=61, Frosinone–Parma, Serie A).** Report text: "makes Frosinone the clear favourite (69%·19%·12%). Expected goals 2.27–0.87." Supporting: "rating gap of +214 Elo points", "#7 (20 pts) vs #16 (8 pts)". Contradicting: "Engine A disagrees by up to 17%". Missing: "bookmaker odds".
- Critique: 69% for the 7th-placed side is well above Engine A's 52%. The Elo of 1629 carries two Serie B seasons, during which the team's results came against weaker opposition (Frosinone fixtures by comp: ITA2 2024/25 = 38, 2025/26 = 38).
- The analyst presents the 17-pp engine gap as one bullet, when it should be the headline. It also presents Elo as support without saying the Elo is cross-league.
- The corners caveat is good and honest, but it is a fixed sentence repeated in all 93 reports that have corners.

**Example 3 (Engine A, predictions.id=29, Bristol City–Wrexham).** Summary: "Most likely outcome: Bristol City (38%)… Main drivers: … **Bristol City score -7% vs a league-average attack**… Confidence is high (74/100)."
- A negative attack rating is listed as a "driver" of Bristol City being favourite.
- The team's form (2W 2D 6L, failed to score in 6) goes unmentioned.
- The text says "concede -7%" (a double negative in another row, Stuttgart). The stored `explanation` string repeats "Expected goals 1.41–1.27" twice.

**Competitors (public user-facing features only; competitor sites were unreachable from this sandbox, so this is based on search-result snippets)**
- SofaScore: an "Attack Momentum" graph showing which team is attacking minute by minute. SofaScore says it is built from events such as dangerous passes, shots, corners and free kicks ([sofascore.com/news](https://www.sofascore.com/news/how-sofascores-attack-momentum-changed-sport-analysis)). Lineups/H2H preview tool ([link](https://www.sofascore.com/news/football-lineups-and-head-to-head-stats-your-ultimate-match-preview-tool)). Team streaks and win-probability "betting insights" ([link](https://www.sofascore.com/ar/news/betting-insights-come-usare-le-serie-delle-squadre-e-i-dati-di-previsione-per-scommesse-di-calcio-piu-intelligenti)).
- FotMob: live xG on match pages, and player xG/xA in the Lineup tab ([fotmob.com/topnews/3627](https://www.fotmob.com/topnews/3627-live-xg-data-is-now-fotmob)). The FAQ says player ratings come from 300+ per-match stats from its stated provider ([fotmob.com/faq](https://fotmob.com/faq)).
- Flashscore: "Match Momentum", a minute-by-minute bar view, described as not shot-only ([flashscore.co.uk/news/momentum](https://www.flashscore.co.uk/news/momentum/YgzwGjeU/)). Live commentary by editors or partners, and sometimes AI for small competitions ([flashscore.com/faq/data](https://www.flashscore.com/faq/data)). Player ratings in lineups ([Flashscore updates](https://www.flashscore.com/news/flashscore-updates/44CN1CsAWSzc94ws)).
- The common pattern: every one of them depends on live event feeds and player-level data, which we do not have. Our edge has to be pre-match probabilistic reasoning and honest comparison against the market, not imitating their live product.

## 3. What is working well
- There are no hallucinated facts. Missing lineups and team news are stated explicitly instead of being assumed (`insights.py:95`, `explain.py:43-44`).
- The three-way comparison of Engine A, Engine B and the no-vig market (`InsightDetail.tsx:63-69`) is genuinely useful, and so is the wording "the market may have information we lack".
- The correct-score matrix and the full market list come straight from the model.
- The corners reliability caveat and the red-card "league base rate" label are honest.
- The live probability model is simple, labelled, and refuses to run on STALE data (`live.py:8-9`).

## 4. What is weak or missing
1. **Calibrated wording.** "High" confidence is used 78% of the time. The validated record is weaker: Engine B's log loss (1.0000) is worse than the market's (0.9819), per the brief's claim, and there are 0 prod validation runs. "Clear favourite" is keyed to the margin only.
2. **Asymmetric factor logic.** Only two of the four attack/defence pairs are evaluated, and draw favourites are mishandled.
3. **No relevance threshold.** Effects of 2% are presented as "main uncertainty".
4. **Low-information boilerplate.** The 1-1 top-score line appears in 86% of reports, the lineups line in 100%, and the corners caveat in 72%.
5. **Unused data.** xG (current season), shots, SOT, HT scores, home/away splits and streaks are all unused in the analyst text.
6. **Cross-league history unlabelled.** Promoted and relegated teams are not flagged.
7. **No post-match review loop.** `eb_evaluations` = 0, and there is no "what we predicted vs what happened".
8. **Too much on screen.** Engine A's explanation and Engine B's report sit on different pages with different vocabularies (internal jargon such as "Dixon-Coles", "Elo").

## 5. Important risks
- **Over-confidence wording misleads users** in a betting-adjacent product. The risk is highest when no odds are present (Frosinone).
- **Template numbers going stale.** The hard-coded validation figures (`insights.py:43`) will drift from the real validation runs.
- **Implying a live feature we cannot deliver.** Momentum or live commentary without an event feed would mean fabricating data.

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| MA-1 | **Calibrated wording.** Favourite label from absolute prob (≥60% strong, 45–60% slight, <45% "open match"). Confidence label capped at "moderate" unless a prod `eb_validation_runs` row shows B beats the market for that league. "Low" when no odds | PARTIALLY IMPLEMENTED | P1 | S | weekly validation job | 0 reports call a <50% favourite "clear"; "high" share ≤ share of leagues where validation beats market; unit test on thresholds |
| MA-2 | **Symmetric factor engine.** Evaluate all 4 attack/defence pairs plus Elo, table and rest. Only include effects ≥10% (or ≥50 Elo). Route draw favourites correctly. Rank by size | PARTIALLY IMPLEMENTED | P1 | S | — | Test fixture: away attack −25% appears as supporting; no bullet <10%; draw-favourite test passes |
| MA-3 | **Preview headline = key tension.** If A/B gap ≥10 pp or the model–market gap ≥8 pp, lead with it. Otherwise lead with the top factor. Drop boilerplate (lineups line moved to a single page-level badge; top score shown only if ≠1-1 or ≥13%) | MISSING | P2 | S | MA-2 | No sentence identical across >50% of reports except labelled badges; Frosinone-type report leads with the 17-pp disagreement |
| MA-4 | **Form comparison panel.** Last 5/10 overall plus home/away splits for both teams side by side: points per game, GF/GA, shots, SOT and xG for/against (xG only 2026/27, 18 leagues, labelled), BTTS/O2.5 counts, streaks (unbeaten/scoreless). Direction arrow "oldest→newest" | PARTIALLY IMPLEMENTED (strings only) | P2 | M | match_stats (have) | Panel renders for 18 football-data.co.uk leagues; xG row hidden with reason where null; matches DB recompute in test |
| MA-5 | **Strengths/weaknesses cards** per team from EWMA percentiles vs the league (attack, defence, shots, SOT, corners, discipline, first-half vs second-half goals from HT scores) | MISSING | P2 | M | features, HT scores (have) | Each card cites metric + league percentile; only leagues with stats; nothing shown for ARG1 stats |
| MA-6 | **Cross-league / small-sample flag.** When >30% of a team's EWMA history comes from another competition (promotion), say so and widen the caveat | MISSING | P1 | XS | features `recent` comp tuple | Frosinone report shows the flag; test with a promoted team |
| MA-7 | **Scoreline and goals view.** Keep the matrix. Add grouped outcomes (win by 1, win by 2+, 0-0, 1-1) and an HT/FT split based on HT history. Label probabilities as model-based | PARTIALLY IMPLEMENTED | P3 | S | — | Grouped probs sum to 1 (test); visible on InsightDetail |
| MA-8 | **xG insight.** Show season xG for/against and "goals minus xG" (luck indicator) for 2026/27; feed it into Engine B only after walk-forward proof | PARTIALLY IMPLEMENTED (data stored, unused) | P2 | S (display) / M (model) | validation | Display for 18 leagues; model change only if log loss improves on walk-forward |
| MA-9 | **Corners/cards.** Keep the caveat but read numbers from the latest `eb_validation_runs`. Show league and team averages plus referee-free base rates; hide the "over X" market rows until the model beats the league mean | PARTIALLY IMPLEMENTED | P2 | XS | validation job | No hard-coded validation numbers in `insights.py`; corners markets hidden when MAE ≥ baseline |
| MA-10 | **Post-match review.** After settlement: predicted vs actual, log loss, which factors held, and how the market moved (closing odds) | MISSING | P2 | M | eb_evaluations populated | Every finished predicted fixture has a review within 24 h; shown on InsightDetail |
| MA-11 | **Match momentum** (minute-by-minute pressure) | BLOCKED BY EXTERNAL DEPENDENCY: needs timestamped events (shots, dangerous attacks) or per-minute stats; we have 0 events. API-Football `/fixtures/events` + `/statistics` is the nearest candidate (key missing, free tier 100 req/day, terms need owner review) | P4 | L | API_FOOTBALL_KEY | Not built until events exist; never synthesised from score alone |
| MA-12 | **Live analysis.** With the free football-data.org feed, show the delayed score plus re-computed live probabilities (already coded) and label them DELAYED. No live commentary | IMPLEMENTED BUT NEEDS VERIFICATION (0 snapshots in prod) | P2 | XS | live cron firing | ≥1 prod snapshot per covered live match; labels correct |
| MA-13 | **Player-level insights** (ratings, top scorers, absences) | BLOCKED BY EXTERNAL DEPENDENCY: `players`=0, `team_news`=0; needs a lineups/injuries source (API-Football) | P4 | L | API_FOOTBALL_KEY, owner approval | — |
| MA-14 | LLM rephrasing of sections | NOT RECOMMENDED now: fix the logic first. If added later, numbers must stay locked (already the documented policy) | P4 | M | MA-1–3 | — |

## 7. Top 3 recommendations
**1. MA-1 calibrated wording.** This is the cheapest fix with the largest trust impact. Today 102 of 130 reports say "high confidence", and 16 call a sub-50% favourite "clear". This happens while Engine B, per the walk-forward claim, does not beat the market and has no production validation record. In a betting-simulation product, overstated certainty is the most misleading thing we can show. Tying labels to absolute probabilities and to validated per-league skill makes every sentence defensible.

**2. MA-2 + MA-6 correct factor logic.** The analyst currently reasons about only half the matchup, ignoring away attack and home defence, and promotes 2% effects to "main uncertainty". It also cannot see that a promoted team's ratings were built in a weaker league. The Frosinone report shows the consequence: a 69% favourite backed by a Serie B-inflated Elo, with the 17-pp disagreement buried. Both fixes are small, testable changes in `insights.py` and `features.py`.

**3. MA-4/MA-5/MA-8 use the data we already have.** Competitors' differentiators (momentum, live xG, player ratings) all depend on event and player feeds we lack. We do hold 23,914 matches of shots, SOT, corners and cards, 2,033 current-season xG rows and 26,698 HT scores, and none of it reaches the user as analysis. Side-by-side form, strengths and weaknesses by league percentile, and xG over- and under-performance would give a pre-match preview real depth without new providers or complex ML.
