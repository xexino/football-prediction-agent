# Roadmap

Ordered by dependency, then priority. Status lives in `PRODUCT_BACKLOG.md`.

| Phase | Theme | Items | State |
|---|---|---|---|
| 1 | Audit & baseline | PRODUCT_AUDIT, test baseline, model baseline | done 2026-11-22 |
| 2 | Reliability & integrity (P0) | A-1…A-6, J-1…J-4 | done; A-7 (observe scheduled runs) open |
| 3 | Data & model quality (P1) | B-1, B-2, F-1, I-1 done · E-4 partial · I-2, I-6, I-7 next | in progress |
| 4 | Coverage (P2) | C-1 done · N-1/D-1 blocked on API-Football key · D-2 (rest/congestion) next | blocked/partial |
| 5 | Product (P3) | L-1, K-1…K-3 done · K-4 Model Lab, M-1 notifications | in progress |
| 6 | Hardening | J-5 migrations, H-1 result corrections, Q-3 | next session |

## Next session (in order)
1. A-7: confirm three consecutive scheduled runs succeeded (Actions history + System Health page).
2. J-5: migration framework (needed before any schema change), then H-1 result corrections.
3. D-2: rest days / fixture congestion as model features — evaluate via walk-forward before adopting.
4. I-2 / I-6: simple-Poisson baseline; revisit 1X2 betting once ≥100 backtest bets exist.
5. If API keys are provided: B-3, then N-1 / D-1 (API-Football adapter: injuries, lineups, CAF, African leagues).

## After v2.0.0 (next five)
1. Add `API_FOOTBALL_KEY` (user action), then verify real live mode, lineups, injuries and the African leagues.
2. Engine B 1X2 improvement (stacking with Engine A or the market), adopted only if it wins out of sample.
3. Corners model: add referee and pace features; adopt only if it beats the league-mean baseline.
4. Persistent live poller (an always-on host) for sub-minute updates. GitHub Actions cron is near-live at best.
5. Optional LLM explanation layer that rephrases only (numbers locked), behind a key.
