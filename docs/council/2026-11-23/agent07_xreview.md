# Agent 7 (Risk) — Cross-review of agent03_ml.md and agent11_growth.md

## Agreements
- **ML-1 ≈ RK-3 / RK-11.** The documented numbers are not in production: there is one `backtest_runs` row and 0 `eb_validation_runs`. ML's further finding strengthens RK-3: the Engine B result of 470 1X2 bets **cannot be regenerated** now that `RISK.markets=("OU25",)`.
- **ML section 2 on the shrink bound.** ML derives `p_c ≤ q+0.015`, which confirms my finding that the strategy mainly selects price differences between bookmakers. Both of us read the "+1.4% CLV / −23.5% ROI" pattern as a red flag (ML risk 3, RK-2).
- **ML-4.** Engine B's `market_shrink=0.25` has no derivation (`engine_b/betting.py:26`). I agree it should be fitted, for example to about 0.17.
- **ML-3.** Promoted teams drop out, which is survivorship bias (133 of 4,978 matches). This adds to my list of statistical traps.
- **GR-1.** I fully agree. Pre-registration (RK-1) means nothing if `gh-pages` is force-pushed (`autopilot.yml:128-137`) and the DB is clobbered. An external timestamp is the missing half of RK-1.
- **GR-7.** I agree. The dashboard text should be framed as probabilities and research, not "tips".

## Disagreements
1. **ML-5's benchmark "BFE/PS closing" is not usable as specified.**
   - PS pre-match rows go to **0 from February 2026** (monthly count: 162 in January, then 0).
   - BFE has corrupt prices: obs 347590 shows a draw at 1.10 against B365 at 3.75, a +69% overround.
   - The benchmark should be a power-de-vigged consensus price (Avg closing), with BFE used only after sanity checks (RK-5).
2. **ML-5's acceptance criteria cannot be met.** It requires "sharp-CLV CI > 0 **and** ROI CI excluding 0" at ≥100 bets. My power calculation shows a +3% ROI needs about 7,800–15,700 bets. Requiring an ROI CI that excludes 0 would never be satisfied at this project's volume. I propose:
   - **Primary:** CLV against consensus closing, net of the random-selection baseline drift. On B365 pre-match vs B365 closing over 10,063 matches, that drift is +0.1% to +0.4% depending on the selection.
   - **Thresholds:** at least 150 O/U bets or 400 1X2 bets.
   - **ROI:** reported as secondary.
3. **GR-5 ("disagreement picks scored afterwards") is a forking-paths risk.** The top-N rule, the value of N and the scoring metric must be fixed in the RK-1 protocol before publication. Otherwise a weekly cherry-picked list will look good by chance. I would keep it at P3 until RK-1 is in place.
4. **GR-2's ClubElo comparator.** ClubElo provides ratings, not 1X2 probabilities. Converting them needs a draw model, which is a choice that can be tuned to flatter or harm the comparator. It belongs at P3. Market and naive are the comparators that matter.

## Wrong statuses / priorities
- **ML-5 status:** it should be PARTIALLY IMPLEMENTED, not MISSING. Same-book CLV fields and their computation already exist (`betting.py:65-77`).
- **GR-1 priority:** P1 is acceptable. However, the integrity of the public record is the product's core claim, so GR-1 should be scheduled together with RK-1, not after growth work.
- **ML-8 (NOT RECOMMENDED):** I agree, based on the paired CI that includes 0.

## Changes to my own recommendations
- **RK-1:** acceptance now also requires GR-1. The rule hash and the predictions/bets ledger must be committed to an append-only branch (no force-push), stamped before kickoff.
- **RK-2:** the benchmark is explicitly *Avg/consensus closing*, with BFE only under the RK-5 checks and PS dropped. Report it with the baseline drift subtracted.
- **RK-3:** acceptance now also requires that the stored Engine B validation can be regenerated from code at the recorded SHA, adopting ML-1. Explicitly add "remove the hard-coded 80/70 quality/confidence values" (`validation.py:130`), as ML also found.
- **RK-6:** add ML's survivorship point. The dashboard must show the share of target matches not predicted.
- **New RK-12 (P3, XS):** any pre-announced "selection lists" (GR-5) must follow a pre-registered rule, with a multiple-comparison note.
