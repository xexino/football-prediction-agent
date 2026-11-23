# ⚽ Football Intelligence Lab

An autonomous football research, prediction and **virtual** betting laboratory. It does the following on its own:

* discovers fixtures;
* collects results, statistics, xG and bookmaker odds from legitimate free sources;
* scores data quality;
* predicts matches with statistical models;
* compares its probabilities with de-vigged market prices;
* places **simulated** €1 bets only when strict value and risk rules pass, and otherwise says **NO BET**;
* settles bets from verified results and tracks performance;
* shows everything in a live dashboard.

> **Simulation only.** No real money, no bookmaker accounts, no deposits or withdrawals, no automatic real bets. Ever.

## Status: partially operational (honest summary)

| Area | State |
|---|---|
| Fixture discovery, results, stats, xG, odds | ✅ **Live** from football-data.co.uk: 38 leagues across Europe, the Americas and Asia, ~47k matches, ~300k odds snapshots |
| Prediction engine | ✅ Dixon-Coles + Elo ensemble. Walk-forward validated: beats the baseline, **does not beat the market** (see `docs/DECISIONS.md`) |
| Value engine / NO BET | ✅ Conservative. Bets only when a bookmaker's price beats the sharp market by more than the margin |
| Virtual bankroll & settlement | ✅ €100 start, €1 flat stake, ≤3 bets/match, AH quarter lines, voids, conflicts held pending |
| Immutability / audit | ✅ Enforced by SQLite triggers. Every prediction stores its inputs, odds snapshot IDs and sources |
| Scheduler, reports, backups | ✅ In-process APScheduler, or GitHub Actions autopilot |
| Dashboard | ✅ 8 pages, reads real DB data only |
| Team news / injuries / lineups | ❌ No free legitimate source. The quality score shows it (0/10) |
| Live in-play data | ❌ None connected. All data is pre-match or periodically refreshed (labelled) |
| UEFA cups, CAF & African leagues, national teams | ⚠️ Fixtures are discovered, but these competitions are **ineligible** (not enough free history/odds). Adding API keys unlocks more |

## AI Match Insights (Engine B), new in v2.0.0
An independent second engine with its own models, records and €100 virtual bankroll. It covers goals, BTTS, totals,
correct score, corners, cards and shots, and writes an evidence-only **AI Match Analyst** report for every fixture.
The release also adds a **live mode** layer (football-data.org delayed scores now; full live data with
`API_FOOTBALL_KEY`) and a global coverage matrix.

See [`docs/AI_INSIGHTS_ENGINE.md`](docs/AI_INSIGHTS_ENGINE.md), [`docs/AI_INSIGHTS_VALIDATION.md`](docs/AI_INSIGHTS_VALIDATION.md),
[`docs/LIVE_DATA.md`](docs/LIVE_DATA.md), [`docs/PROVIDER_COMPARISON.md`](docs/PROVIDER_COMPARISON.md) and
[`docs/AI_INSIGHTS_OPERATIONS.md`](docs/AI_INSIGHTS_OPERATIONS.md).

## Quick start (any machine with Python 3.11+ and Node 18+)

```bash
scripts/install.sh
```

```bash
scripts/start.sh
```

Then open <http://localhost:8000>. On an empty database the scheduler bootstraps itself: it imports history
(about 10 minutes) and then runs the daily cycle. Docker alternative: `docker compose up -d --build` (data lives in `./data`).

The dashboard is built into `backend/fil/static` and served by the same process as the API.

### Useful commands (run from `backend/`)

| Command | Purpose |
|---|---|
| `python -m fil serve` | API + dashboard + scheduler |
| `python -m fil job daily` | Full cycle: results → fixtures/odds → settle → retrain → predict → coverage → report → backup |
| `python -m fil job fixtures_odds` / `results` / `prematch_review` / `weekly` | Single jobs |
| `python -m fil backtest --step 14` | Walk-forward backtest |
| `python -m fil backup` / `python -m fil restore <file>` | Backup / restore |
| `python -m fil export-static ../site` | Read-only dashboard snapshot (for GitHub Pages) |
| `python -m pytest -q` | 110 backend tests (Engine A + Engine B, reliability, integrity, live, security, API) |
| `node frontend/e2e/smoke.cjs http://localhost:8000` | Browser end-to-end test of all 8 pages + mobile layout (Playwright) |

## Configuration

Copy `.env.example` to `.env`. **Every key is optional.**

| Variable | Effect |
|---|---|
| `FOOTBALL_DATA_ORG_KEY` | Adds football-data.org fixtures/results (Champions League etc.) |
| `ODDS_API_KEY` | Adds The Odds API prices (more books; UEFA competitions) |
| `API_FOOTBALL_KEY` | Enables the API-Football **live** adapter (`fil/engine_b/live.py`: score, minute, events, statistics; implemented and mock-tested, never run against the real API). There is **no** API-Football adapter yet for fixtures, lineups, injuries or African leagues. Add a quota guard before setting the key (see `docs/AI_PRODUCT_COUNCIL_ROADMAP.md`, DP-1) |
| `FIL_ADMIN_TOKEN` | Enables `POST /api/admin/run/{job}` with header `X-Admin-Token`; disabled when empty |
| `FIL_SCHEDULER=0` | Disables the in-process scheduler (e.g. when cron or Actions drives jobs) |

Value and risk thresholds live in `backend/fil/config.py` (`ValueRules`, `RiskRules`).

## Autonomous operation on GitHub (free)

`.github/workflows/autopilot.yml` runs the daily cycle at 05:10 UTC, plus fixtures/odds and results every 3 hours.
It keeps the database as the `db-latest` release asset and publishes a read-only dashboard to <https://xexino.github.io/football-prediction-agent/> (branch `gh-pages`).

**One-time setup:**
1. Nothing for Pages: the workflow pushes the dashboard to the `gh-pages` branch (Settings → Pages should show "Deploy from branch: gh-pages").
2. Settings → Actions → General: allow workflows to run.
3. Optional: add the API keys above as repository secrets.

## Data, backups, transfer

| What | Where / how |
|---|---|
| Database | `data/fil.db` (SQLite, WAL mode) |
| Backups | `data/backups/fil-<UTC timestamp>.db.gz`: made daily, 14 kept; also `scripts/backup.sh` |
| Restore | `scripts/restore.sh data/backups/<file>.db.gz` |
| Transfer to another machine | Copy the repo plus `data/fil.db` (or a backup), run `scripts/install.sh`, then `scripts/start.sh` |
| Dataset snapshot | `data/snapshot/fil.db.gz` (if present) is the DB built at launch. To start from it: `gunzip -c data/snapshot/fil.db.gz > data/fil.db` |

## Dashboard pages

| Page | Contents |
|---|---|
| Overview | Bankroll, P/L, ROI, open bets, upcoming, model status |
| Upcoming | Every fixture with odds, form, model probabilities, xG, quality, value table and reasons |
| Predictions | All predictions, including NO BET, with explanations, sources and revisions |
| Virtual Bet Slip | Open bets and rules |
| Results & History | Filterable ledger with settlement evidence and CLV |
| Analytics | Live and backtest metrics, calibration, drawdown, segments |
| Data Sources | Providers, status, quota, errors, per-competition coverage and eligibility |
| System Health | Jobs, next runs, DB, errors, reports |

Docs: [audit](docs/PRODUCT_AUDIT.md) · [backlog](docs/PRODUCT_BACKLOG.md) · [roadmap](docs/ROADMAP.md) · [data sources](docs/DATA_SOURCES.md) · [model validation](docs/MODEL_VALIDATION.md) · [operations](docs/OPERATIONS.md) · [changelog](docs/CHANGELOG.md). Design rationale is in [`docs/DECISIONS.md`](docs/DECISIONS.md): environment assessment, sources, models, validation
results, quality score, risk and settlement rules, and limitations.

Data attribution: football-data.co.uk, TheSportsDB, martj42/international_results (CC0).
