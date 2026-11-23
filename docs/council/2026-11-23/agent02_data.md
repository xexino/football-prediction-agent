# Agent 2 — Senior Football Data Scientist

All numbers come from read-only queries on `council/prod.db` (snapshot 2026-11-23 00:49 UTC) unless marked otherwise. The code was read at commit 3a1ead6.

## 1. Current situation
The DB holds 58,771 fixtures (56,496 finished, 2,273 scheduled) across 52 competitions, plus 25,571 `match_stats` rows, 347,658 odds snapshots, 57,990 result observations and 1,316 teams. The base for goals markets in the 22 football-data.co.uk (fd.co.uk) "main" leagues is strong. Coverage outside those leagues is thin. The biggest problem is not missing statistics: team identity resolution is fragmenting team histories.

## 2. Evidence

**Coverage (fixtures by competition and season, from the `GROUP BY` query)**
- 22 main fd.co.uk leagues (ENG1–5, ESP1–2, ITA1–2, GER1–2, FRA1–2, NED1, POR1, BEL1, TUR1, GRE1, SCO1–4) run from 2023/24 to now, about 3.3 seasons.
- 15 "extra" leagues (ARG1, BRA1, USA1, MEX1, JPN1, CHN1, POL1, ROU1, SWE1, NOR1, DEN1, AUT1, SUI1, IRL1, FIN1) run from 2022 with results only.
- International competitions run from 2016 (8,393 rows from `intl_results`).
- UCL has 663 fixtures. UEL, UECL, CAF and the North African leagues have 1–17 fixtures each.
- Season labels are inconsistent within a single league. ENG1 has `2026/27` (fd.co.uk), `2026` (football-data.org), `2026-2027` (thesportsdb) and `''` (205 fixtures from fd.co.uk fixtures.csv; `footballdata_uk.py:207,225` sets `season=""`). No model uses `season` (grep: only `ingest.py:169,185`, `collect.py:248`), so this hurts standings and reporting, not predictions.

**match_stats completeness** (all from source `football_data_uk`)
| Field | Matches | Competitions |
|---|---|---|
| shots, SoT, corners, fouls | 23,914 | 22 |
| yellow/red cards | 25,571 | 22 (ENG5 2023–26 has cards only) |
| xG | 2,033 | 18 (2026/27 only; none for ENG5, SCO2–4) |
| HT score | 26,698 of 56,496 finished | missing in all extra leagues and internationals |

There are no stats for the 15 extra leagues, internationals or UCL. Outliers are rare: 4 rows with SoT > shots, 4 with corners > 20, 2 with xG > 6.

**Home/away splits** (finished club matches since 2023-07)
- Mean home-minus-away goal difference ranges from 0.166 in ITA1 to 0.449 in CHN1 (BRA1 0.416, USA1 0.395, ENG1 0.251).
- Home win rate ranges from 0.40 to 0.48.
- Engine B uses one global `ELO_HOME=55` (`engine_b/features.py:25`).

**Odds** (all from fd.co.uk)
- Closing 1X2: 47,321 fixtures. Pre-match: 25,846. Pinnacle closing: 35,813.
- O/U 2.5 and AH: about 25.8k fixtures, all in the 22 main leagues. The 15 extra leagues have closing 1X2 only (`footballdata_uk.py:188-191`).
- No BTTS, corners, cards, shots or player odds exist anywhere. `extra` JSON is always empty.
- Upcoming fixtures: only 21 of 141 fixtures in the next 7 days have any odds, and UCL has 0 of 18.
- Sanity: 25 `Avg` closing rows have overround < 1.0, which looks like a data error.
- `value_assessments`: 529 of 621 have no bookmaker, meaning there was no price to assess.

**Result observations**
- 1,392 fixtures have more than one source. Only 1 disagrees: fixture 55108, two `intl_results` rows on the same day (2-1 and 5-0) collapsed into one fixture by `DUP_WINDOW` = 36 h (`ingest.py:24`).
- `result_conflict` = 0 everywhere.
- Freshness: 192 fixtures dated 2026-11-20 to 23 are still `scheduled`, waiting for fd.co.uk's twice-weekly update. In most extra leagues the last finished match is 2026-11-08.

**Standings:** 212 rows, a single snapshot (2026-11-22, football-data.org) for 10 competitions only. There is no history, so standings cannot be used as a walk-forward feature.

**Identity resolution** (the main finding)
- **UCL/UEL/UECL teams are a separate population.** 135 teams have `country='Europe'`. At least 45 of them have an exact-name domestic twin (Arsenal/England vs Arsenal/Europe, Real Madrid, Inter, and so on; fuzzy scan with `teamnames.normalize`). Cause: football-data.org is a non-primary source, and candidates are restricted to teams already seen in UCL (`ingest.py:113`), so domestic teams are never considered. Engine B still issues 13 UCL predictions (mean data quality 43) from this disconnected Elo pool, and domestic rest days ignore European midweek games.
- **A national team is merged with a club.** Team 217 "Andorra" (Spain, club) has 98 ESP2 fixtures and 102 national-team fixtures (UNL/WCQ/INTFR). `teamnames.py:62` accepts any alias match when `country==""`, which is how `intl_results` calls it.
- **Wrong cross-source match.** The alias `athletic` maps to `Atleti` with confidence 0.857. As a result, "Atleti" has two UCL fixtures on 2026-01-21 (vs Galatasaray and vs Atalanta) and two on 2026-01-28.
- **Renames inside fd.co.uk split teams.** Examples: Ham-Kam (to 2023-09) / HamKam; Din. Bucuresti (to 2026-02) / Dinamo Bucuresti; Gornik Z. (to 2023-03) / Gornik Zabrze. Each split resets Elo and form.
- **Cross-source duplicate teams.** Sabah Baku / Sabah FK, and Qarabağ / Qarabağ Ağdam.
- **Duplicate fixtures.**
  - Four pairs have the same competition and kickoff and share a team (Rennes v Paris SG and Rennes v "Paris FC" on 2026-08-23, both 2-2; Viking v Sabah, and others).
  - Three neutral-venue international pairs have reversed home/away, for example Euro 2024 QF Germany–Spain 1-2 (`intl_results`, includes extra time) vs Spain–Germany 1-1 (football-data.org, 90 minutes). Both rows feed Elo.
  - 15 cases of a team playing twice on the same date.
- **Low-confidence aliases.** 81 aliases have confidence < 1.0 (44 football-data.org, 37 thesportsdb). There is no review queue.

**Promotion cold-starts:** 131 league entrants appear with no prior DB history and start at Elo 1500. In their first 10 matches they average 1.08 PPG and −0.40 goal difference per match (n = 1,277 team-matches), against a league average of about 1.37 PPG and 0. This means a newcomer is systematically overrated.

**Referees:** the source CSVs have them. A live header check (2026-11-23) found `Referee` in E0, E1, E2, EC and SC0 (2025/26), E0 2023/24, and E0 and SC1 2026/27. It is absent from D1, SP1, I1 and F1. E0 2025/26 has a referee on 380 of 380 rows (23 distinct). `extract_stats` does not parse it (`footballdata_uk.py:101-112`).

**Players and team news:** both tables have 0 rows.

## 3. What is working well
- fd.co.uk ingestion is complete and consistent for the 22 main leagues: statistics fill about 99.9% of rows, and closing odds are present for 98%.
- Multi-source result verification works: 1,379 matches are confirmed by two or more sources with zero disagreements, and extra-time handling is explicit (`ingest.py:236-244`).
- Features in `features.py:77-102,105-140` are built strictly pre-match (state is updated after each row), so they are leakage-safe.
- The odds snapshots are append-only and hashed, and `Max`/`Avg` are excluded as non-bookable (`value.py:18`).
- Engine B honestly labels red cards and player markets as unavailable (`engine_b/model.py:109-111`).

## 4. What is weak or missing
- Team identity: the European-cup island, national/club merges, rename splits, the `athletic` → Atleti mis-map, and duplicate fixtures (details in section 2).
- There is no integrity check for "team plays twice within 36 h" or for reversed-orientation duplicates.
- The 15 extra leagues and all internationals have no statistics, no HT scores and no O/U odds.
- No odds exist for BTTS, corners or cards, so value and CLV cannot be measured for those markets.
- Pre-match odds for upcoming fixtures appear only 1–3 days before kickoff, and only when fd.co.uk publishes `fixtures.csv`.
- Referee data is available in English and Scottish files but is not ingested.
- Domestic cups are not ingested, so rest and congestion features are incomplete.
- Standings have no history.
- Season labels are not normalised.

## 5. Important risks
1. UCL predictions and any UCL value bets rest on a 663-match isolated rating pool. Performance there will not resemble the walk-forward results measured on domestic leagues.
2. The club/national merges and wrong matches contaminate Elo for real league teams (FC Andorra in ESP2) without any warning.
3. Duplicate fixtures double-count results in Elo and Dixon-Coles, and they escape conflict detection because each duplicate has only one source.
4. Corners, cards and BTTS cannot be shown to have an edge without odds. Presenting value for them would be unsupported.

## 6. Market data sufficiency
| Market | Model data | Market (odds) data | Verdict |
|---|---|---|---|
| 1X2 | 56,496 results | 47,390 finished with odds; 35,813 Pinnacle closing | Sufficient (22+15 leagues) |
| O/U goals 2.5 | 56,496 results | 25,767 fixtures, main leagues only; no other lines | Sufficient for 22 leagues; model-only elsewhere |
| BTTS | 56,496 results | 0 | Calibration only; no value |
| Corners | 23,914 matches | 0 | Data sufficient; model showed no skill (MAE 2.730 vs 2.723 baseline, claimed) |
| Cards | 25,571 matches, no referee | 0 | Model only; referee could help (ENG/SCO) |
| Shots/SoT | 23,914 matches | 0 | Model only |
| Player markets | 0 players | 0 | Insufficient. Keep disabled. |

## 7. Candidate features (each needs a walk-forward A/B before adoption)
The common protocol: rerun the walk-forward on the same matches as current (claimed 4,845 matches, Aug 2025–Nov 2026), plus a per-league breakdown. Compute the per-match log-loss difference (B′ − B) and its paired bootstrap 95% CI. Adopt only if the mean Δ ≤ −0.002 and the CI excludes 0, with no league worse by more than 0.01.

- **Opponent-adjusted form.** Data exists (goals, SoT, corners). Today's EWMA uses raw for/against values (`features.py:111-115`). Measurement: EWMA of (actual − expected given the opponent's rating). A/B on 1X2 and O/U log loss.
- **Rest days / congestion.** The feature already exists (`features.py:97-98`) but is biased, because European and cup matches are missing for domestic teams. Measurement: the share of matches whose rest-day value changes after the identity fix. A/B only after DS-1.
- **Home advantage by league.** Data exists: the spread is 0.17–0.45 goals. Replace the global Elo `ELO_HOME` with a shrunk per-league value. A/B on 1X2, with extra weight on BRA1, CHN1 and USA1.
- **Promotion/relegation.** Data exists: 131 cold-starts. Seed a newcomer's Elo at the 20th percentile of its league's Elo. A/B on matches involving entrants in their first 15 games, plus overall.
- **Referee.** Present for ENG and SCO only (about 9 divisions, roughly 11k matches). Use a shrunk referee yellow-card rate. A/B on the cards negative-binomial log-likelihood and MAE, restricted to ENG and SCO.
- **xG.** Exists for 2026/27 only (2,033 matches). Defer until there is at least one full season, then A/B Engine B with xG EWMA.
- **Manager changes, weather, travel.** No data source and no venue coordinates. NOT RECOMMENDED now.

## 8. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| DS-1 | Link UCL/UEL/UECL teams to domestic identities: resolve football-data.org European-cup names against all teams of the participating countries, then merge the `Europe` twins | MISSING | P0 | M | none | 0 `Europe` teams with a normalised domestic twin; ≥95% of UCL fixtures have both teams with ≥20 domestic matches |
| DS-2 | Stop national/club alias capture: in `teamnames.py:62`, require `team.is_national == is_national`; split team 217 | MISSING | P0 | S | none | No team has fixtures in both international and club competitions (currently 1, with 102+98) |
| DS-3 | Identity integrity checks: team plays twice within 36 h; orientation-insensitive duplicates on neutral venues; review queue for aliases with confidence < 0.9; manual alias map for fd.co.uk renames | PARTIALLY IMPLEMENTED (`merge_duplicates` only) | P0 | S | DS-2 | Same-day double-play = 0 (now 15); same-kickoff duplicates = 0 (now 4+3); HamKam/Dinamo/Gornik unified; `athletic` alias fixed |
| DS-4 | Run the production walk-forward and store a per-league breakdown (`eb_validation_runs` = 0); reuse it as the feature A/B harness with a paired bootstrap | PARTIALLY IMPLEMENTED | P1 | S | DS-1–3 | One stored run with per-league log loss, Brier and ECE; A/B script outputs Δ and CI |
| DS-5 | Newcomer Elo prior (bottom-quintile seed) | MISSING | P1 | S | DS-4 | Entrants' first-15-game log loss improves with CI excluding 0; overall not worse |
| DS-6 | Per-league home advantage in Engine B Elo | MISSING | P1 | XS | DS-4 | Protocol above |
| DS-7 | Parse `Referee` (ENG/SCO) and run a cards A/B | MISSING | P2 | S | DS-4 | ≥95% of ENG/SCO rows have a referee; cards NB log-likelihood improves with CI excluding 0, otherwise keep the column unused |
| DS-8 | Odds for upcoming fixtures and secondary markets (The Odds API free tier, key needs owner approval) | BLOCKED BY EXTERNAL DEPENDENCY | P1 | M | key | ≥80% of next-7-day main-league fixtures have pre-match odds 24 h before kickoff; UCL covered |
| DS-9 | Normalise season labels to `YYYY/YY` or `YYYY` per competition | MISSING | P3 | S | none | 1 label format per competition-season; 0 empty seasons |
| DS-10 | Validate odds and stats at ingest (overround < 1.0 on `Avg`, SoT > shots) | MISSING | P2 | XS | none | 25 + 4 rows flagged; excluded from the market baseline |
| DS-11 | Opponent-adjusted form features | MISSING | P3 | M | DS-4 | Protocol above |
| DS-12 | Manager, weather and travel features | NOT RECOMMENDED | P4 | L | new sources | Not applicable until a free source with history exists |

## 9. Top 3
1. **DS-1 (European-cup identity).** 135 separate "Europe" teams mean every UCL/UEL/UECL prediction, and the rest days of the biggest domestic clubs, rests on a disconnected 663-match rating pool. That breaks the core promise that predictions draw on full team history. The fix stays inside the resolver plus a one-off merge, and it unlocks honest evaluation of European matches.
2. **DS-2 and DS-3 (identity integrity).** The national/club merge, rename splits, the `athletic` → Atleti mis-map and 7 duplicate fixtures corrupt Elo and Dixon-Coles without any warning, and conflict detection cannot see them because each duplicate has only one source. Cheap checks (same-day double play, reversed orientation, alias review) make the data self-auditing. They should run in `integrity.py` and appear on the health page.
3. **DS-4, then DS-5 and DS-6 (measured feature work).** No production validation run exists yet. Building the A/B harness first turns every feature idea into a go/no-go decision with a CI. The two cheapest candidates have measured signal in this DB: newcomers concede 0.40 goals per match relative to their 1500 seed, and home advantage varies 2.7× across leagues. Corners, cards and BTTS should stay "model only, no value" until odds exist (DS-8).
