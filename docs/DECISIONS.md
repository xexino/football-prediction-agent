# Technical decisions & methodology

## 1. Environment assessment (build time, 2026-11-22)

| Item | Finding |
|---|---|
| Machine | Linux x86_64 cloud container, 4 vCPU, 15 GB RAM, ~60 GB free disk |
| Runtimes | Python 3.13, Node 22, no Docker daemon |
| Network | Egress via an allow-list proxy. Football hosts were blocked at first; a dedicated environment (`football-prediction-agent`) now allows football-data.co.uk, football-data.org, The Odds API, API-Football, TheSportsDB and ClubElo |
| Background processes | Supported while the session is alive |
| Persistence | **Not durable.** The container is reclaimed after inactivity, so anything not pushed to git is lost |
| Public URL | None. The container cannot expose a public port |

**Consequence:** the app runs and is tested in the container, but continuous autonomous operation is handed to
**GitHub Actions** (free for public repositories) via `.github/workflows/autopilot.yml`:
* the SQLite database persists as a release asset (`db-latest`), plus a 90-day artifact per run;
* jobs run on a schedule;
* a read-only dashboard snapshot is published to **GitHub Pages**.

The same code runs unchanged on any machine through `scripts/start.sh` or Docker.

## 2. Data sources (all checked for real access, Nov 2026)

| Source | Access | Used for | Notes |
|---|---|---|---|
| **football-data.co.uk** | Free CSV, no key | Results 2023→now for 22 European divisions + 16 extra leagues (BRA, ARG, MLS, J1, …); shots, corners, cards, **xG** (2026/27); pre-match **and closing** odds from Bet365, Pinnacle, bwin, Betfair Exchange, market avg/max; 1X2, O/U 2.5, Asian handicap; **weekly fixtures file with current odds** | Primary source. Updated ~2×/week, not live. Times are UK local time and converted to UTC |
| **TheSportsDB** (public key `123`) | Free, heavily limited (~1–15 events per call) | Fixture discovery and result cross-checks, incl. UEFA cups, CAF, Egypt, Morocco, South Africa, Tunisia | Too little history for modelling, so those competitions are reported as ineligible |
| **martj42/international_results** (GitHub, CC0) | Free | National-team results (AFCON, WC qualifiers, Nations League, Copa América, Asian Cup) | No upcoming fixtures or odds |
| football-data.org | Free key required | Fixtures/results incl. Champions League | Adapter ready; activates when `FOOTBALL_DATA_ORG_KEY` is set |
| The Odds API | Free key required (500 credits/month) | Odds incl. Champions League | Adapter ready; activates when `ODDS_API_KEY` is set |
| API-Football | Free key required (100 req/day) | Injuries, lineups, African leagues, live scores | Registered but **not implemented**; it is the main upgrade path for team news |
| ClubElo | Connection reset by the host | — | Not used |

No authentication, paywall, rate limit or terms of service is bypassed. Requests are spaced politely, cached
on disk (`data/cache`), retried with backoff, and fall back to stale cache during outages (labelled as such).

## 3. Architecture

```
providers/*  ──►  ingest.py (dedupe ±36h, team-name resolution, result verification, append-only odds)
                     │
                     ▼
               SQLite (WAL) — immutable ledger tables protected by triggers
                     │
models/engine.py (Dixon-Coles per league + Elo/ordered-logit) ──► pipeline.py ──► value.py ──► betting.py
                     │                                                   │
              backtest.py (walk-forward)                    quality.py (0-100) / coverage.py
                     │
scheduler.py (APScheduler, Europe/Rome) ── jobs.py ── reports.py / backup.py
                     │
api.py (FastAPI) ──► React + TypeScript + Recharts dashboard (served by the same process)
```

* **SQLite instead of PostgreSQL.** There is a single writer and the data is small (~100 MB), and SQLite needs zero ops,
  backs up to one file and moves easily. SQLAlchemy keeps a PostgreSQL migration simple.
* **One process.** API, static dashboard and scheduler run in one uvicorn process. A lock prevents overlapping jobs.
* **Immutability enforced by the database, not just by code.** SQLite triggers abort:
  * any UPDATE of core prediction, bet or odds fields;
  * any DELETE on the ledger tables;
  * any change to an already settled bet;
  * any bet whose `created_at >= kickoff`.

## 4. Models

1. **Dixon-Coles**, fitted per competition:
   * time decay ξ = 0.0019/day (half-life ≈ 1 year) over a 3-year window;
   * ridge prior on team parameters, with a weaker prior for newly promoted teams;
   * the Poisson term uses 0.5·goals + 0.5·xG when xG exists;
   * analytic gradient, L-BFGS-B. All 37 leagues fit in about 2 s.
2. **Elo** (K = 20, home advantage 65, goal-difference multiplier):
   * promoted and relegated teams are re-seeded against their new league;
   * ratings map to 1X2 through an **ordered logit** fitted on past matches.
3. **Ensemble:** 0.6·DC + 0.4·Elo for 1X2. The DC score matrix is rescaled to the ensemble 1X2, so every derived
   market is consistent: DC, DNB, O/U 0.5–4.5, BTTS, team goals, AH and correct score. Mutually exclusive outcomes sum to 1.
4. **Confidence** is reported separately from probability: 40% data quality, 35% agreement between DC and Elo,
   25% sample size.

## 5. Validation (walk-forward, no look-ahead)

11 leagues, Aug 2025 → Nov 2026, refit every 14 days, 4,859 out-of-sample matches:

| Model | Log loss | Brier | Accuracy |
|---|---|---|---|
| Baseline (league H/D/A frequencies) | 1.0763 | 0.6514 | 43.2% |
| Elo | 0.9954 | 0.5941 | 50.6% |
| Dixon-Coles | 0.9980 | 0.5958 | 50.9% |
| **Ensemble** | **0.9947** | **0.5937** | **51.3%** |
| Market (de-vigged pre-match odds) | 0.9817 | 0.5853 | 52.4% |

The model is much better than the baseline but **worse than the betting market**, as expected for free data
without team news.

### The value-rule decision (documented, not tuned for profit)
* **First run**, with model probabilities shrunk 50% toward the market: 2,046 bets, ROI **−8.0%**
  (1X2 longshots −17%). The model was trusted far too much.
* **Blend scan:** the log-loss-optimal mix `w·model + (1−w)·market` is **w ≈ 0.10**. It was fitted on the first half
  of the period and confirmed on the second half (0.9785 vs 0.9786 at w = 0). The model adds only a little
  information beyond the market.
* **Rule change:** `market_shrink = 0.10` (taken from the log-loss scan, not from P/L) and conservative-EV threshold
  +2%. With these rules a bet happens only when a named bookmaker's price beats the sharp reference
  (Betfair Exchange or Pinnacle) by more than the margin, plus a small model contribution.
* **Second run** under the final rules: 65 bets, ROI −22%, average CLV +1.8%. At 65 bets the ROI standard error is
  about ±20%, so the sample is too small for any conclusion. The engine does **not** claim profitability.

Both backtest runs are stored in `backtest_runs` and shown on the Analytics page. The ensemble-weight scan
(DC vs Elo) is flat between 0.2 and 0.6, so the 0.6/0.4 default stays; it was not re-tuned.

## 6. Data-quality score (0–100)

| Component | Max points |
|---|---|
| Source reliability | 10 |
| History sample (min of both teams, 8→40 matches) | 20 |
| Recency | 10 |
| Odds markets (1X2/OU/AH × number of books, capped) | 15 |
| Odds quality (margin + cross-book dispersion) | 10 |
| Odds freshness | 10 |
| Stats/xG depth | 10 |
| Team-name match confidence | 5 |
| Team news | 10 |

No team-news source is connected, so no match scores above 90. Bets need ≥ 70. Counting distinct markets
(not websites) avoids rewarding repeated copies of the same underlying information.

## 7. Bet selection & risk

A selection must pass every filter:
* quality ≥ 70 and confidence ≥ 55;
* each team has ≥ 20 matches in the competition;
* odds between 1.50 and 5.00;
* bookmaker margin ≤ 9%;
* odds snapshot ≤ 96 h old;
* a sharp market reference exists;
* the model–market gap is ≤ 15 pp (a larger gap probably means missing information, e.g. injuries);
* the bookmaker's price is consistent with the reference (catches corrupt rows);
* conservative EV ≥ +2%.

Then:
* at most one bet per market per match;
* never 1X2 and AH on the same match (they are correlated);
* at most 3 bets per match and 15 per day;
* flat €1 stake from a €100 virtual bankroll;
* no Martingale, no chasing, no forced bets.

If nothing qualifies, the prediction is stored with **"NO BET — no sufficiently reliable value opportunity identified."**

## 8. Settlement rules
* **General:** settled on the result at 90 minutes plus stoppage time, and only when it is verified with no conflict
  between sources. Conflicting sources keep the bet **pending**.
* **Postponed, cancelled or abandoned:** void (stake refunded) if not played within 48 h of the original kickoff.
* **1X2 and O/U 2.5:** standard rules.
* **Asian handicap:** whole lines can push; quarter lines split into two half-stakes.

CLV is measured against the same bookmaker's closing price.

## 9. Known limitations
* No team news, injuries or lineups (needs an API-Football key plus implementation). Quality scores reflect this.
* No live data. Everything is pre-match or periodically refreshed (labelled in the UI).
* UEFA club competitions, CAF and the African domestic leagues are **ineligible**: there are not enough free
  historical results and odds. The coverage page shows exactly why. Adding API-Football or football-data.org keys
  is the route to cover them.
* football-data.co.uk publishes results about twice a week, so settlement can lag 1–4 days.
* Corners, cards, half-time and player markets are not offered: no free odds or reliable settlement data.
