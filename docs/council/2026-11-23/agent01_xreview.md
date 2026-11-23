# Agent 1 (Product) — cross-review of Agent 2 (Data) and Agent 8 (UX)

## Agree
* **UX-2 + UX-4 (canonical match page, source chip on every number).** These deliver the same thing as my PM-4 "Lab view", and the UX version is easier to ship. Agent 8 found that Instituto–Huracan shows xG 1.1–0.9 on one page and 1.52–1.06 on another, with nothing saying which engine produced which. That strengthens my point that users get no single answer.
* **UX-3 (4 task-based sections) and UX-7 (lead with evidence, collapse the €0 tiles).** These match PM-1. I adopt UX-3's structure in place of my vaguer "nav ≤7 items".
* **UX-1 should be P0.** The simulation disclaimer is hidden on mobile (`styles.css:83`), which undermines the integrity brand. I missed it.
* **DS-1, DS-2, DS-3 at P0.** The 135 "Europe" teams, the Andorra club/national merge and 7 duplicate fixtures all go straight into a public track record. My PM-2 scorecard would publish contaminated numbers for UCL and the affected teams.
* **DS-4 (production validation run with per-league breakdown).** This is what PM-2 and UX-7 need before Engine B's track-record page can show anything honest.

## Disagree / adjust
* **UX-14 (live view) at P3 is fine, but it should also be gated on evidence.** Without a minute-level provider, a live strip shows "0 live" forever. Do not build it ahead of the key.
* **DS-8 (The Odds API) should be P1 for the product, but not to revive value betting.** It matters for the *market benchmark* in the track record, because the market is the reference that makes the scorecard meaningful. It needs owner approval. I would set its acceptance criterion as "market probability available for ≥80% of evaluated predictions", not just "odds present".
* **DS-7 (referee) and DS-11 (opponent-adjusted form).** I agree with the priorities, but from a product view these come after the integrity fixes. None of them change what a user sees in 0–3 months.
* **UX-9's acceptance criterion (4/5 users explain "conf · quality") is untestable today.** There are no users, no analytics and no test panel (UNKNOWN). I suggest "every abbreviation has a tooltip, verified by an e2e check" as the measurable criterion and the user test as optional.

## Status/priority corrections
* **UX-12 / my PM-8 (provider-status contradiction):** both reports confirm it independently. Merge them into one item at P2.
* **UX-5 (suppress EV on flagged odds):** should be **P0**, not P1, under the brief's own definition ("integrity"). Showing "Draw −71.0%" as analysis is misleading output, and the fix is XS.
* **UX-10 / my PM-9 (payload size):** duplicates. UX-10's target of "≤1.5 MB/hour idle" is the better metric, because polling a 1.07 MB file with `no-store` every 120 s costs about 32 MB/hour.

## Changes to my own report
1. **Corrected the odds-coverage figure.** I wrote "74 of 141 fixtures in the next 7 days have odds". Agent 2's 21/141 is right. I re-ran the query with kickoff between 00:49 on 2026-11-23 and 7 days later: 21 fixtures with any odds, 16 with a bookable B365/PS/BW price. My 74 included past-dated fixtures still marked scheduled. Fixed in `agent01_product.md` (evidence table and coverage metric: now 15%, target ≥70%).
2. **PM-2 acceptance criteria will add a precondition:** DS-1–3 resolved, or UCL and the affected teams shown as "excluded / identity under review".
3. **PM-4 will be delivered through UX-2/UX-4.** A blended headline probability stays optional and needs out-of-sample proof first.
4. **Roadmap at 3 months adds UX-1 and UX-5 (P0, XS) and DS-1–3** ahead of PM-5.
