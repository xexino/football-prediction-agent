# CFO report: 2026-11-25

> **Owner decision (2026-11-25):** the CFO is paused. The rule changes proposed below were **not** applied; the current rules (€500 capital, €10 flat stakes, existing value filters) stay as they are. This report is kept for reference only.

*Simulation only: virtual money. Sources: prod DB snapshot (21:22 UTC) and a walk-forward re-run on a DB copy (2025-08-01 → 2026-11-25, model 1.1.0, live rules), which reproduces the stored run exactly (40 bets, −29.7 %). Amounts assume €10 stakes.*

**Bottom line.** No edge has been shown; the best evidence says it is negative. Against the de-vigged sharp **closing** line, the backtest bets are worth **−3.4 %** each (n = 29 with a closing reference; 95 % CI ≈ [−6.0 %, −0.8 %]). The "+1.2 % CLV" we have been quoting compares each bet with Bet365's own closing price and flatters us.

## 1. P&L to date
| | Engine A | Engine B |
|---|---|---|
| Capital put in | €500.00 (€100 initial + €400 top-up, 25 Nov 21:21) | €500.00 (€100 + €400 top-up) |
| Cash / equity | €498.00 / €500.00 | €500.00 / €500.00 |
| Bets placed / settled | 2 / 0 | 0 / 0 |
| Stakes | €2.00 (2 × €1, old stake size) | €0 |
| Open exposure | €2.00 (worst case −€2, best case +€6.83) | €0 |
| Realised profit, ROI, CLV, hit rate | €0.00; none of the others is defined yet | none |

The two open bets:
1. Doncaster v Huddersfield (ENG3), home @ 4.50.
2. Cremonese v Avellino (ITA2), away @ 4.33. Kick-off was 25 Nov 18:00; the result is not yet ingested.

Both are 1X2 longshots, our worst segment (§4), in leagues with **no walk-forward evidence**. Model EV +11 % to +23 %; against the market reference, about +1 %.

Live predictions: 34 evaluated, 58.8 % accuracy, log loss 1.017 vs market 1.028; noise at n = 34. Top-ups are capital, not income; ROI is measured on stakes.

## 2. Unit economics of a €10 bet (backtest portfolio, n = 40)
| Item | Value |
|---|---|
| Average odds (median) | 2.90 (2.69) |
| Implied probability (1/price) | 38.4 % |
| Market fair probability (de-vigged reference) | 39.2 % |
| Model probability | 42.8 % (+3.6 pp vs market) |
| Bookmaker overround on the book | 5.6 % (1X2 6.6 %, OU 5.3 %, AH 4.4 %) |
| Cost of a random €10 bet at our prices | −€0.60 (−6.0 % ROI across 34,653 priced selections) |

| Expected value of €10 under… | EV |
|---|---|
| (a) the model | **+€1.16** (+11.6 %) |
| (b) the market, pre-match reference | +€0.22 (+2.2 %) |
| (b′) the market, sharp **closing** line | **−€0.34** (−3.4 %) |
| (c) the backtest, realised | **−€2.97** (−29.7 %; CI −€6.35 to +€0.81) |

The model claims five times the edge the market grants; the closing line erases the rest (prices move ~5.6 points against us before kick-off).

## 3. Forecast (Monte Carlo, 20,000 paths)
**Assumptions:**
* **Volume:** about 20 bets/month at the live rate (2 bets in 3.0 days; the Poisson CI is 2–72/month).
* **Odds:** drawn from the backtest odds distribution.
* **Stakes and bankroll:** €10 flat from €500.
* **Ruin:** the balance falls below €10.

Scenarios:
* **Central −3.5 %:** clean closing-line value (CLV).
* **Pessimistic −10 %:** model-led 1X2 selections in the broad universe lose 13 %.
* **Stress −30 %:** the backtest point estimate.
* **Break-even 0 %.**
* **Optimistic +3 %.**

| Scenario | 6 m mean [P10, P90] | P(profit) / ruin | 12 m mean [P10, P90] | P(profit) / ruin | 24 m mean [P10, P90] | P(profit) / ruin |
|---|---|---|---|---|---|---|
| −30 % | −€349 [−495, −179] | 1 % / 21 % | −€483 | 0 % / 91 % | −€495 | 0 % / 100 % |
| −10 % | −€120 [−307, +70] | 21 % / 0.7 % | −€234 [−493, +26] | 12 % / 16 % | −€380 [−498, −106] | 5 % / 60 % |
| **−3.5 %** | **−€42 [−232, +150]** | **39 % / 0.2 %** | **−€79 [−358, +195]** | **35 % / 4.5 %** | **−€158 [−495, +219]** | **28 % / 22 %** |
| 0 % | −€1 [−195, +193] | 49 % / 0.1 % | +€1 | 50 % / 1.8 % | +€7 [−454, +398] | 50 % / 9.7 % |
| +3 % | +€36 [−156, +235] | 59 % / 0 % | +€73 [−205, +351] | 63 % / 0.7 % | +€144 [−249, +542] | 68 % / 3.9 % |

Even a genuine +3 % edge leaves one path in three in the red after 480 bets. At the backtest rate (2.5 bets/month) the 24-month central loss is −€21 with ~0 ruin: volume amplifies whatever the true edge is.

**What volume of evidence is needed:**
* **ROI:** one bet's outcome has a standard deviation of 1.38 stakes, so a ±3 % ROI CI needs about **8,100 bets**, about 34 years at our volume.
* **Clean CLV:** its standard deviation is 7–9 %, so ±2 % needs about **50 bets** and ±1 % about **200 bets**. **CLV is therefore the only KPI that can decide anything within a year.**

## 4. Where the money is lost
**Strategy bets (n = 40, −11.86 units = −€118.60 at €10):**

| Segment | n | ROI | Loss at €10 |
|---|---|---|---|
| **1X2** | 22 | **−43.4 %** | −€95.50 |
| ↳ home / away | 7 / 3 | −67.9 % / −100 % | −€77.50 |
| ↳ draw | 12 | −15.0 % | −€18.00 |
| AH | 15 | −15.4 % | −€23.10 |
| OU2.5 | 3 | 0 % | €0 |
| **Odds 3.5–5.0** | 13 | **−73.1 %, CI [−100 %, −19 %]**: the only CI that excludes 0 | −€95.00 |
| Odds 1.5–3.5 | 27 | −8.7 % | −€23.60 |

Leagues (n = 2–8 each) are noise.

**Broad universe:** all 34,653 priced selections with a market reference.
* **Model disagreement is an anti-signal.** Selections where the model sees value (EV > 0) return **−7.8 %**, worse than betting at random (−6.0 %). The ROI falls steadily as the model–market gap widens:

| Gap, model above market | 0–2 pp | 2–4 pp | 4–6 pp | 6–10 pp | 10–15 pp | > 15 pp |
|---|---|---|---|---|---|---|
| ROI | −1.3 % | −5.4 % | **−10.3 %** | −8.3 % | −10.9 % | −15.4 % |

  From 4 pp upwards every confidence interval excludes 0.
* **1X2 home and away with model EV > 0:** −17.4 % and −16.9 %, with CIs about [−25 %, −9 %]. Draws: −1.3 %, CI [−12 %, +10 %].
* **AH and OU with model EV > 0:** −3.5 % and −5.0 %, the same as betting everything (−3.6 %, −5.2 %): we just pay the margin.
* **Odds above 5.0:** −22 %.
* **Conservative-EV filter (n = 462):** −0.1 % realised, −1.9 % clean CLV: the shrink limits damage, creates no edge. Optimal out-of-sample model weight: **w = 0.00**.

## 5. CFO mandates
**Redefine success.**
* **80–99 % match accuracy is not achievable.** The market, our ceiling, picks the right 1X2 outcome **52.6 %** of the time (n = 4,955; 46.8 % ENG2 to 56.6 % GER1). Our model gets 51.2 %; a naive baseline gets 43.3 %.
* **High-confidence picks are rare and short-priced.** 25 % of matches are draws. Favourites at ≥ 70 % cover 11.9 % of matches and hit 80.5 %; at ≥ 80 %, 3.8 % of matches, 83.5 %. Those prices (~1.15–1.40) leave nothing after margin.
* **Success is measured in money:** first a positive clean CLV, then ROI ≥ 0 with a CI, with the bankroll preserved. Accuracy is not reported as a goal.

**KPIs and gates:**
1. **Clean CLV** (bet price vs de-vigged closing price, PS → plausible BFE → Avg) on every settled bet, in both the ledger and the backtest.
   * **Target:** ≥ +1.0 %.
   * **Freeze gate:** at 50 settled bets, an upper 95 % bound below 0 freezes the strategy.
   * **Graduation gate:** at 200 bets, the lower bound must be above 0.
   * Stop citing CLV against the same bookmaker's own close.
2. **ROI:** always reported with a bootstrap CI. It is not used to justify any change below 1,000 bets. At 100 bets or more, an upper CI bound below 0 is a red flag.
3. **Maximum drawdown:** 30 % of capital (€150).
4. **Stop-loss:** if Engine A or Engine B equity drops below **€350**, new placements for that engine are suspended. They resume only after a council review with CLV evidence. Top-ups never reset the stop, and no further top-ups are made without a council decision.
   * At 20 bets/month it trips within 12 months with probability 47 % (0 % ROI), 61 % (−3.5 %), 83 % (−10 %). Intended.
5. **Exposure:** Engine A new exposure ≤ €50/day (today's 15 bets/day = €150, the whole drawdown budget).
6. **Evidence before a rule change:**
   * **Risk-reducing changes:** allowed immediately.
   * **Risk-increasing changes:** a pre-registered paired walk-forward on ≥ 4,000 matches, plus a clean-CLV CI excluding 0 or ≥ 200 backtest bets. Live results under 200 bets never justify loosening.

**Stop now (risk-reducing):**
* Engine A **1X2 home and away selections**. This matches Engine B, which disabled 1X2 at −23.5 % with a significant CI.
* **Odds above 3.50**.
* **Leagues outside the 11 backtested ones.** Both live bets fall in this category.
* **Model–market gaps above 4 pp**. They are treated as model error.
* **Prices older than 24 h.** The last pre-match odds are from 24 Nov 14:18 UTC; bet #2 used a price 22 h old.

**Test next (shadow ledger only):**
1. **Market-only price shopping** (w = 0): bet only when a bookable price beats the sharp fair price by ≥ 2–3 %, judged by clean CLV. 14 of the 40 bets were of this kind (−16.5 % vs −36.7 % for model-led).
2. **1X2 draws** as a pre-registered hypothesis, since they are the only 1X2 segment near break-even.
3. **Bet timing:** +2.2 % pre-match becomes −3.4 % at the close; measure the move, test later placement.
4. **Engine B OU2.5** (114 backtest bets, −2.7 %, CI [−26 %, +23 %]). Recompute it with clean CLV and apply the 50- and 200-bet gates.
5. **Model work** targets the log-loss gap to the market (+0.0155, CI [+0.0117, +0.0192]), not accuracy; power calibration (t = 1.09) merits a paired test.

No changes to stakes, no Martingale, no loss-chasing: flat €10, and never increased after losses.
