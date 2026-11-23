# Engine B — validation

Walk-forward run on 2026-11-23 using a copy of the production database:
* 11 leagues (ENG1/2, ESP1, ITA1, GER1, FRA1, POR1, NED1, BEL1, TUR1, SCO1), 2025-08-01 to 2026-11-23;
* both engines refit every 14 days on data strictly before each step;
* every model scored on the **same 4,845 matches**.

## 1X2
| Model | Log loss | Brier | Accuracy | ECE |
|---|---|---|---|---|
| Naive (league frequencies) | 1.0768 | 0.6517 | 43.2% | 0.0041 |
| Simple Poisson (league means only) | 1.0766 | 0.6519 | 42.8% | 0.0082 |
| **Engine B** | 1.0000 | 0.5973 | 50.6% | 0.0157 |
| **Engine A** | **0.9949** | **0.5939** | **51.3%** | 0.0120 |
| Market (de-vigged pre-match) | 0.9819 | 0.5858 | 52.3% | 0.0098 |

Engine B is **worse than Engine A on 1X2** and both are worse than the market.

## Goal markets
| Market | Engine B | Engine A | Market |
|---|---|---|---|
| Over/Under 2.5 log loss | **0.6805** | 0.6858 | 0.6759 |
| BTTS log loss | **0.6861** | 0.6871 | — |

Engine B is better than Engine A on totals and BTTS. It is still behind the market on totals.

## Corners and cards (4,779 matches with statistics)
| | Engine B | League-mean baseline |
|---|---|---|
| Corners: mean absolute error of total | 2.730 | **2.723** |
| Corners: Over 9.5 log loss | 0.6909 | 0.6911 |
| Corners: 80% interval coverage | 84.3% | — |
| Cards: mean absolute error of total | **1.633** | 1.640 |
| Cards: Over 3.5 log loss | **0.6774** | 0.6811 |
| Cards: 80% interval coverage | 86.7% | — |

* **Corners:** no measurable skill over the league average. This is stated on every match report.
* **Cards:** a small gain.
* **Intervals:** slightly wide (84–87% coverage against a nominal 80%).

## Simulated selections (Engine B rules, historical)
| Segment | Bets | ROI | 95% CI | Avg CLV |
|---|---|---|---|---|
| All | 584 | −19.5% | −31.5% … −7.5% | +1.5% |
| 1X2 | 470 | −23.5% | −36.7% … −9.8% | +1.4% |
| O/U 2.5 | 114 | −2.7% | −26.0% … +23.4% | +1.9% |

1X2 selections lost money with statistical significance, so they are **disabled**. This is a risk-rule decision; the model
itself is unchanged. O/U 2.5 is inconclusive. **No profitable edge is claimed.**

## Leakage controls
* Features are pre-match by construction (tested).
* Training uses only rows with kickoff before the step date.
* Closing odds are used only to compute CLV after a bet, never as features.

## Reproduce
```bash
cd backend && python -c "from fil.engine_b import validation; validation.run()"
```
The weekly autopilot job also runs it and stores the result in `eb_validation_runs`, shown on the Engine B track-record page.
