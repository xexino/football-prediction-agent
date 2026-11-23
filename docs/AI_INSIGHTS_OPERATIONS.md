# AI Match Insights — operations

## Jobs (GitHub Actions autopilot)
| Schedule (UTC) | Job | Engine B steps |
|---|---|---|
| 05:10 daily | daily | `eb_retrain`, `eb_settle`, `eb_evaluate`, `eb_predict`, `eb_live` (after Engine A's steps) |
| every 3h at :40 | results + fixtures_odds | `eb_settle`, `eb_evaluate`, `eb_predict`, `eb_live` |
| every 20 min, 11:00–23:59 | live | `eb_live` |
| Monday 06:25 | weekly | `eb_validation` (walk-forward Engine A vs B) |

Every Engine B step is **non-critical**: if one fails, the run is marked PARTIAL, but Engine A's critical steps and the
database persistence are unaffected.

Run a job manually:
```bash
cd backend && python -m fil job engine_b
```
```bash
cd backend && python -m fil job live
```

## Secrets
| Secret | Needed for | Status |
|---|---|---|
| `FOOTBALL_DATA_ORG_KEY` | fixtures, standings, CL, delayed live score | configured (verified) |
| `API_FOOTBALL_KEY` | real live mode (minute, events, statistics), lineups, Africa and Asia | **not set**: create it in GitHub → Settings → Secrets and variables → Actions |
| `ODDS_API_KEY` | more bookmakers | not set |

## Database
* New `eb_*` tables are created by `init_db()` on start-up. The upgrade only adds tables and triggers; nothing is
  altered or dropped (`test_migration_adds_engine_b_tables_without_touching_data`). It was tested on a copy of the
  production database: integrity OK, and Engine A's row counts were unchanged.
* The persistence guard also refuses to save a database where any Engine B ledger or prediction table shrank.
* Integrity checks cover the Engine B bankroll chain and the stake/bet reconciliation.

## Troubleshooting
| Symptom | Cause | Action |
|---|---|---|
| Live tab empty | no matches in play, or only the free provider available | normal; add `API_FOOTBALL_KEY` for real live data |
| "COVERAGE ONLY" on a competition | not enough history or odds | needs a provider with history for it (API-Football) |
| Engine B predicts no match in a league | teams have < 6 matches in our data | resolves as data accumulates |
| `eb_*` step failed in a run | see System Health → run details | Engine A unaffected; fix and re-run `job engine_b` |
