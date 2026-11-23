# Agent 8 (UX) — Cross-review of Agent 1 (Product) and Agent 4 (Match Analysis)

## Agreements
- **PM-1 (fewer than 7 navigation items, ops pages grouped)** matches UX-3. Both reports independently measured the same 12-item navigation (`main.tsx:21-26`).
- **PM-2 (Track Record page)** matches UX-7. PM-2 should own the metrics and UX-7 the page layout: empty-state collapse, sample size shown on every tile.
- **PM-8 (trust papercuts)** matches UX-12. We independently found the same contradiction: `coverage_matrix` says football_data_org is not configured, while `health_detail` says it is (`desk_coverage.png` shows "AWAITING KEY" next to "79m ago").
- **PM-3 at P0** is right. Every UX freshness indicator is meaningless if scheduled runs never fire.
- **MA-1 (calibrated wording)**, **MA-3 (remove boilerplate)** and **MA-6 (cross-league flag)** are all correct. I saw the same "clear favourite at 47%" and "Main uncertainty: concede 2% less" text on the Instituto detail page (`desk_DETAIL_full.png`).
- **MA-11 and MA-13 (BLOCKED)** are right. The UI must never fake momentum.

## Disagreements and corrections
1. **PM-4 "single Lab view" headline (P1).** I disagree with this as a near-term UX change.
   - Merging the engines into one number hides the gap between A, B and the market. MA-3 shows that gap is often the most informative headline (Frosinone: A/B gap of 17 percentage points).
   - With no production validation (`eb_validation_runs` = 0), there is no evidence-based rule for blending.
   - Proposed instead: show the market (no-vig) as the anchor when odds exist, with A and B as labelled deviations next to it (UX-4). Blend only after PM-2 has a track record. Priority should be **P2**, with a dependency on validation.
2. **PM-9 (slim payloads) should be P2, not P3.** Payload size alone understates the cost. `api.ts:18` uses `cache: "no-store"`, and Upcoming polls every 120s (`Upcoming.tsx:82`). That re-downloads the 1.07 MB file about 30 times an hour, roughly 32 MB per hour per open tab, on the mobile audience the product is aimed at. Merge PM-9 into UX-10.
3. **PM-1 "ops pages under Lab internals".** I partly disagree.
   - The freshness and health summary and the SIMULATION ONLY notice are integrity signals, not internals. They must stay visible on every page. Today CSS hides them on mobile (`styles.css:83`), which is UX-1 at P0.
   - The coverage matrix ("which leagues we can cover") is user-facing. Only the System and Sources tables belong under internals.
4. **MA-4, MA-5 and MA-8 (new panels).** I agree on the value but not on placement. The detail page is already 1,859px tall on desktop and 3,445px on mobile, and includes an 11-bullet "Not available" list. New panels need the tabbed match page from UX-2 (Summary / Form / Markets / Odds / Review). Otherwise depth turns into clutter. Add as a dependency: **UX-2**.
5. **Conflicting backtest ROI.** PM-1 and PM-2 cite Engine A's 65 bets at −25%, but the live Overview and Analytics pages show **−22.0%** for the same 65 bets. One figure, from one source, should be cited everywhere. This needs verification by the ML agent.
6. **MA-12 status "IMPLEMENTED BUT NEEDS VERIFICATION"** is accurate. From the UI side, "0 live" appears on every view (`desk_insights.png` pill), consistent with 0 snapshots in the database.

## Changes to my own recommendations
- **UX-3:** adopt PM-1's grouping. Four user sections (Matches, Track record, Simulation, Coverage) plus a collapsed "Lab internals" group (System, Sources).
- **UX-4:** card and detail headlines use MA-1's calibrated words ("slight favourite", "moderate confidence") instead of raw "conf 75 · quality 65". Raw numbers move to the tooltip.
- **UX-9:** add MA-3's deduplication. The always-present lineups line and the "Not available" list collapse into a single row of badges at page level.
- **UX-10:** absorbs PM-9. Priority stays **P2**.
- **New UX-15 (P2, S):** a "Review" tab on the match page that displays MA-10's post-match review (predicted vs actual, log loss, closing odds). It depends on `eb_evaluations` being populated.
- **UX-14 (live strip):** lowered from P3 to **P4**, consistent with MA-11 and PM-10. Nothing meaningful can be shown until a minute-level provider exists.
