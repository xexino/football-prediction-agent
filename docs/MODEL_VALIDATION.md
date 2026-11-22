# Model validation

Latest walk-forward run (2026-11-22, model `fil-ensemble 1.0.0`) covers 11 leagues (ENG1/2, ESP1, ITA1, GER1, FRA1,
POR1, NED1, BEL1, TUR1, SCO1) from 2025-08-01 to 2026-11-22. Models are refit every 14 days on data strictly before
each step. There are 4,861 out-of-sample matches.

## 1X2 probability quality

| Model | n | Log loss | Brier | Accuracy | ECE |
|---|---|---|---|---|---|
| Baseline (league H/D/A frequency) | 4861 | 1.0763 | 0.6514 | 43.2% | 0.0036 |
| Dixon-Coles | 4861 | 0.9981 | 0.5959 | 50.9% | 0.0100 |
| Elo + ordered logit | 4861 | 0.9955 | 0.5942 | 50.6% | 0.0114 |
| **Ensemble (deployed)** | 4861 | **0.9949** | **0.5938** | 51.3% | 0.0117 |
| Market (de-vigged pre-match odds) | 4860 | 0.9819 | 0.5855 | 52.4% | 0.0088 |

By season, the ensemble scored log loss 1.0005 in 2025/26 (n = 3,729) and 0.9766 in 2026/27 (n = 1,132). The
2026/27 figure covers the season in which xG is available.

### Reliability of the favourite's probability
| Predicted range | n | Mean predicted | Observed |
|---|---|---|---|
| < 0.40 | 893 | 37.8% | 41.0% |
| 0.40–0.50 | 1825 | 44.7% | 43.1% |
| 0.50–0.60 | 1136 | 54.5% | 52.5% |
| 0.60–0.70 | 611 | 64.5% | 69.6% |
| ≥ 0.70 | 396 | 77.1% | 80.6% |

Strong favourites are slightly under-predicted, probably because the ridge shrinkage pulls team ratings toward the mean.

### Calibration experiment (E-4)
I tested power calibration `p^t / Σ p^t`. Fitted on the first half of the period, it gave t = 1.025. On the second half
(n = 2,430) log loss moved from 0.9933 to 0.9931 and ECE from 0.0074 to 0.0071. The gain is within noise, so it is
**not deployed**. The weekly backtest re-runs the check.

### Model vs market blend
The log-loss-optimal mix `w·model + (1−w)·market` is **w ≈ 0.10**, fitted on the first half and confirmed on the second.
The model adds only a little information beyond the market. The value engine's market-shrink weight is set from this
scan, never from betting profit.

## Simulated value strategy (live rules, flat 1 unit)
| Segment | Bets | ROI | ROI 95% CI (bootstrap) | Avg CLV |
|---|---|---|---|---|
| All | 65 | −25.2% | −51.4% … +2.5% | +1.8% |
| 1X2 | 29 | −45.3% | −88.3% … +2.2% | +1.5% |
| O/U 2.5 | 24 | −10.5% | −53.1% … +32.9% | +2.4% |
| Asian handicap | 12 | −6.1% | −55.4% … +45.4% | −0.1% |

**Interpretation.** No profitable edge is demonstrated. The sample is far too small, and every interval except the
overall one includes zero. The overall interval only just includes zero, and its estimate is negative. Positive average
CLV is a weak encouraging signal and nothing more. 1X2 bets are the weakest segment; this will be re-evaluated at
≥ 100 bets (backlog I-6).

An earlier rule set (50% shrink) produced 2,046 bets at −8.0% ROI. That result is why the rules were tightened.

## Leakage controls
* Training uses only matches with `kickoff < step date`. The Elo ordered logit is fitted on pre-match rating differences.
* Strategy prices are pre-match snapshots. Closing odds are used only for CLV, after the bet.
* Live predictions store `training_cutoff`, the odds-snapshot IDs used, the model version, and an inputs hash.
  Predictions and bets are immutable (SQLite triggers).

## Reproduce
```
cd backend && python -m fil backtest --step 14
```
The results are also stored in `backtest_runs` and shown on the Analytics page.
