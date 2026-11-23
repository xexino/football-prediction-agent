# Agent 8 — UX/UI and Dashboard Product Designer

Reviewed commit `3a1ead6` (verified with `git rev-parse HEAD`) and the live site on 2026-11-23, around 00:50–01:10 UTC. Screenshots are in `council/shots/` (`desk_*.png` at 1440×1000, `mob_*.png` at 390×844, `*_full.png` are full-page). I opened and looked at them before making the judgements below.

## 1. Current situation
The dashboard is a single-page React 18 + Recharts app using HashRouter. It has 13 routes in two sidebar groups. The first group has 8 Engine A pages: Overview, Upcoming, Predictions, Virtual Bet Slip, Results & History, Analytics, Data Sources and System Health. The second group, "AI MATCH INSIGHTS", has 4 Engine B pages: Match Insights, Engine A vs B, Engine B record and Global coverage. The whole frontend is about 1,333 lines of code. The look is a dense, dark trading-terminal style with monospace numbers. It runs in static-snapshot mode on GitHub Pages. No settled bets exist yet, so every performance page currently shows empty states.

## 2. Evidence
- **Navigation is split into two parallel worlds.** The split is defined in `frontend/src/main.tsx:21-26` (`NAV` and `NAV_AI`). The same fixture shows up in four places, each with a different pattern:
  - **Upcoming** (`desk_upcoming.png`): a table row that expands inline (`Upcoming.tsx:115`).
  - **Overview**: a table with no link.
  - **Match Insights**: a card that links to `#/insights/:id` (`Insights.tsx:46`).
  - **Compare**: a link (`Compare.tsx:26`).

  The Engine A pages never link to the Insight detail page. A grep for `insights/` finds it only in `pages/ai/*`.
- **The same match shows conflicting numbers.** Instituto–Huracan has xG **1.1–0.9** on Upcoming (Engine A) and **1.52–1.06** on Insights (Engine B). The 1X2 split is 43/31/26 on one and 47/27/26 on the other. Neither page says which engine produced its numbers.
- **The Engine B record page has an unkept promise.** `Compare.tsx` says "The walk-forward comparison on 4,845 historical matches is on the Engine B track-record page." That page (`desk_engine-b.png`) shows only empty states. The validation card only renders `{v && …}` (`EngineB.tsx:38`), and live `data/engine_b/performance.json` has `"validation": null`. This matches the brief: 0 rows in `eb_validation_runs`.
- **Bad odds are shown as analysis.** On Upcoming, Sepsi–Rapid shows odds `1.09 / 1.08 / 1.11` and "Draw −71.0%" with an `ODDS ERROR` badge. Bragantino–Vasco and Buyuksehyr–Corum carry the same badge (`desk_upcoming.png`).
- **Mobile layout breaks on several routes.**
  - The page scrolls sideways at 390px. Measured `scrollWidth` values: home 594, coverage 868, system 567, analytics 1214. The causes are tables outside `.tablewrap` (measured: Overview upcoming table 563px, provider tables 837px and 536px) and the raw-JSON "Model versions" row on Analytics.
  - The nav becomes one horizontal strip showing only "Overview / Upcoming / Predictions" (`mob_home.png`). Nothing shows that 9 more items exist.
  - `styles.css:83-84` hides both `.sim-banner` (the SIMULATION ONLY disclaimer and the data-freshness block) and `.nav-sec` on mobile.
  - Upcoming on mobile clips the model probabilities, quality and status columns off-screen (`mob_upcoming.png`).
  - On mobile, every KPI tile takes the full width. You have to scroll about 1,000px past six "€0.00 / —" tiles before reaching anything useful (`mob_home.png`, `mob_analytics.png`).
- **Accessibility gaps.**
  - Clickable rows are `<tr onClick>` with no `tabIndex`, `role` or key handler (`Upcoming.tsx:115`, `Predictions.tsx:45`), so keyboard users cannot open them.
  - There is no `:focus-visible` style in `styles.css`.
  - The source has no `aria-` attributes at all (grep).
  - Body text is 13px, and many labels are 10–11px (`th` is 10.5px, `.badge` 10.5px, `.nav-sec` 10px).
  - `--faint` #4f5e6d has a contrast ratio of **2.73:1** on panels and **2.85:1** on the sidebar (computed), below the WCAG 4.5:1 minimum. `--muted` passes at 5.28:1.
  - The Insights tab buttons show their selected state only through inline border colour (`Insights.tsx:34`), with no `aria-pressed`.
  - A Tab-key walk on `#/upcoming` cycled through the 12 nav links and back to the top without reaching the filters (Playwright run). This needs a manual check.
- **Performance.**
  - The JS is one 691,722-byte chunk (191,869 bytes gzipped). There is no route-level code splitting: all 13 pages and Recharts are imported eagerly (`main.tsx:7-19`).
  - Data files are large: `data/upcoming.json` is **1,073,456 bytes**, `predictions.json` 309 KB and `insights.json` 157 KB.
  - `api.ts:18` fetches with `cache: "no-store"`, and Upcoming polls every 120s (`Upcoming.tsx:82`). One open tab therefore re-downloads about 32 MB per hour of a snapshot that changes only about every 3 hours.
- **Charts.** The Analytics "Model comparison" bar chart's y-axis starts at 0.9 (`desk_analytics_full.png`). That makes baseline 1.076 look about 4× worse than ensemble 0.995. The ECE column is all "—", and "ROI 95% CI" says "n/a".
- **Inconsistent numbers.** Overview shows backtest strategy ROI **−22.0% (65 bets)**, while the brief and docs quote −25% for the same 65-bet strategy. Comparing across pages, Analytics reports 4,859 matches and Compare reports 4,845.
- **System and Coverage confuse the reader.**
  - Coverage lists both providers as `AWAITING KEY`, yet football_data_org shows "last success 79m ago" (`desk_coverage.png`). The brief says FOOTBALL_DATA_ORG_KEY is configured.
  - System shows 9 green HEALTHY tiles while the sidebar says "scheduler off".
  - System shows a CI runner path (`/home/runner/work/...`).
- **No error handling.** `Loading` (`ui.tsx:95`) only shows "Loading…" or a raw error string. There is no skeleton, no retry button and no error boundary.

## 3. What is working well
- **Honest empty states.** For example, "NO BET — no sufficiently reliable value opportunity identified. That is a successful decision, not a failure." This is a strong trust pattern, and it should be kept.
- **The Insight detail page is the best page in the product** (`desk_DETAIL_full.png`). It has:
  - a clear 1/X/2 headline;
  - an A vs B vs market table;
  - the analyst text, with "Supports / Could make it wrong / Missing" columns;
  - a correct-score heatmap;
  - an explicit "not available" list.

  The coverage badges (FULL / PARTIAL / COVERAGE ONLY / UNAVAILABLE) are also clear.
- **Freshness is shown openly.** The sidebar shows "data as of 78m ago", and `FreshnessBanner` (`main.tsx:30`) warns after 8 hours.
- **Insight cards (desktop) are scannable.** They show the favourite outlined, xG, BTTS and O2.5 on one line, and the Engine A split in the footer for comparison.
- **The visual system is consistent:** colour tokens on `:root`, a single CSS file and a tiny dependency set.

## 4. What is weak or missing
1. **The information architecture is built around engines, not user tasks.** A visitor has to know what "Engine A" and "Engine B" mean before they can find a match. A "Predictions" page and a "Match Insights" page side by side is confusing.
2. **There is no single canonical match page.** The best page (Insight detail) cannot be reached from Upcoming, Overview or Predictions.
3. **Mobile works poorly:** hidden nav items, the hidden simulation disclaimer, page-level sideways scrolling, clipped tables and huge KPI stacks.
4. **Empty performance pages dominate.** Overview, Analytics and the Engine B record lead with rows of €0.00 and "—". The walk-forward evidence that does exist is either buried far down Analytics (Engine A) or missing entirely (Engine B).
5. **There is no glossary or explanation of terms** such as xG, BTTS, O2.5, conf, quality, CLV, ECE, no-vig and log loss. The analyst text is good but is written for experts.
6. **Live display is inert:** "0 live" in every view, with only a key-missing message.
7. **Accessibility and performance gaps:** see section 2.

## 5. Important risks
- **Misleading output.** Odds flagged as errors still produce a "Best value" figure (−71%). Two engines give different xG for the same match with no label saying which engine produced which.
- **The SIMULATION ONLY disclaimer is invisible on mobile** (`styles.css:83`). That matters for the product's integrity promise.
- **Truncated axes** in Analytics overstate how much the models differ.
- **Bandwidth and battery cost on phones** from about 1 MB of polling every 2 minutes.

## 6. Recommendations
| ID | Recommendation | Status | Priority | Effort | Dependencies | Acceptance criteria |
|---|---|---|---|---|---|---|
| UX-1 | Show the SIMULATION ONLY disclaimer and the data-freshness status on mobile: a compact sticky top strip ("Simulation · data 78m ago ●") instead of `display:none` | MISSING | P0 | XS | – | At 390px the disclaimer is visible on every route without scrolling; e2e smoke asserts it |
| UX-2 | Make one canonical match page `#/match/:id`, built from InsightDetail plus an Engine A tab (odds table, value assessments). Every fixture row or card (Overview, Upcoming, Predictions, Insights, Compare, History) links to it as a real `<a>` | PARTIALLY IMPLEMENTED (InsightDetail exists for B only) | P1 | M | match ids shared across A and B (already the same `id`) | 100% of fixture rows are anchors to `#/match/:id`; no `<tr onClick>` remains |
| UX-3 | Reorganise navigation by task, with engines as labels instead of sections: **Matches** (merged Upcoming + Insights, a Live/Upcoming/Results tab), **Track record** (Analytics + Engine B record + Compare, with an engine switch), **Simulation** (Bet slip + History), **Data & health** (Sources + Coverage + System). That gives 4 top-level items instead of 12 | MISSING | P1 | M | UX-2 | Nav ≤5 items; any fixture reachable in ≤2 clicks from home; old hash routes redirect |
| UX-4 | Label every number with its source: an "A"/"B"/"Market" chip next to each probability or xG, plus a consistent colour per engine (A = blue, B = violet) | PARTIALLY IMPLEMENTED | P1 | S | – | No probability or xG appears without a source label; Instituto–Huracan no longer shows two unlabeled xG values |
| UX-5 | Suppress value and EV outputs when odds are flagged (`ODDS ERROR`/suspect): show "odds unreliable — excluded" instead of "Draw −71.0%" | PARTIALLY IMPLEMENTED (badge only) | P1 | XS | backend flag already exists | No EV is displayed for fixtures with suspect odds |
| UX-6 | Fix mobile layout: wrap all tables in `.tablewrap`; on ≤760px render Upcoming and Compare as cards (reuse `.ai-card`); use a bottom tab bar for the 4 sections from UX-3; show KPI tiles in a 2-column grid; wrap or collapse the raw JSON | MISSING | P2 | M | UX-3 | `scrollWidth ≤ 390` on all 13 routes at 390px (Playwright assertion); probabilities visible without sideways scrolling |
| UX-7 | Honest track-record page: when n=0, collapse the €0/— tiles into one line ("No settled bets yet · first results expected after …"), and lead with the walk-forward validation for both engines (Engine A data exists; for Engine B, publish `eb_validation_runs` or remove the false cross-reference in `Compare.tsx`) | PARTIALLY IMPLEMENTED | P1 | S | weekly validation job writing `eb_validation_runs` (Agent ops) | No page links to content that does not render; Engine B page shows validation or an explicit "validation not yet run in production" message |
| UX-8 | Accessibility pass: `:focus-visible` outline; anchors instead of row click handlers; `aria-pressed` on tab buttons; raise `--faint` to at least #8695a4 (≥4.5:1); minimum font size 12px, body 14px; `<main>` landmark plus a skip link | MISSING | P2 | S | – | axe-core run in e2e shows 0 serious or critical issues; all interactive elements reachable by Tab |
| UX-9 | Plain-language layer: a hover/tap glossary (ⓘ) for xG, BTTS, conf, quality, CLV, log loss, no-vig; a one-sentence summary at the top of each card ("B favours Instituto; A and the market agree") | PARTIALLY IMPLEMENTED (analyst text) | P2 | S | – | Every abbreviation in cards has a tooltip; first-time-user test: 4 of 5 people correctly explain "conf 75 · quality 65" |
| UX-10 | Performance: `React.lazy` per route (Recharts only in the chart pages); in static mode drop `no-store` and poll only `health_detail.json`, re-fetching other files when `computed_at` changes; split or trim `upcoming.json` | MISSING | P2 | S | – | Initial JS ≤ 90 KB gzipped; a static tab downloads ≤ 1.5 MB/hour while idle |
| UX-11 | Chart honesty: start the log-loss bars at a stated baseline (e.g. "difference vs market" bars around 0), or switch to a dot plot; hide the all-"—" ECE column; label "ROI 95% CI n/a" with a reason | PARTIALLY IMPLEMENTED | P2 | XS | – | No truncated-axis bar charts; no all-empty columns |
| UX-12 | Make provider status consistent: one status vocabulary shared by Coverage and System (configured / delayed / live / missing key), with the scheduler state reflected in health tiles; hide internal runner paths | PARTIALLY IMPLEMENTED | P2 | S | backend health semantics (Agent ops) | football_data_org is not shown as "AWAITING KEY" while it succeeds; no `/home/runner` path on the public UI |
| UX-13 | Error and loading states: skeleton cards, a "Retry" button, a per-route error boundary, and a friendly message for 404 or missing JSON | MISSING | P3 | S | – | A simulated 404 on a JSON file shows a recoverable message, not raw text |
| UX-14 | Live view (when a minute-level provider exists): a pinned "Live now" strip on Matches with minute, score and in-play probability, following the common score-app pattern of live first, then today, then upcoming | BLOCKED BY EXTERNAL DEPENDENCY (API_FOOTBALL_KEY, owner approval) | P3 | M | API key | Live matches appear at the top within one refresh cycle |

Comparison with common public patterns in football score and stats apps (no claims about their internals):
- Lists are grouped by **date, then competition**.
- A tap on a match opens **one match page** with tabs (Summary / Stats / Odds / H2H).
- Navigation is a **bottom tab bar** on mobile.

The product already has the parts for this structure. It just spreads them across two engine-shaped sections.

**Example interaction after UX-2/3/4.** A user opens *Matches → Today*. They tap "Instituto vs Huracan" and land on `#/match/47588`. The headline reads "B 47% · A 43% · Market 47% — Instituto". Tabs are Summary (analyst text), Markets, Odds & value (Engine A) and History. A ⓘ next to "quality 65" explains "how complete the input data is". From the same page, a "Track record of these engines →" link opens the merged Track record page.

## 7. Top 3 recommendations
1. **UX-2 + UX-4: one match page with labelled numbers.** This is the biggest gain in understanding. Today the same match appears in four layouts with contradictory, unlabeled numbers (xG 1.1–0.9 vs 1.52–1.06), and the best page in the product cannot be reached from the main Upcoming list. One canonical page, with a source chip on every number, turns "which number is right?" into "here is how A, B and the market differ". This is mostly rewiring existing components, so the effort is medium.
2. **UX-1 + UX-6: fix mobile, starting with the hidden disclaimer.** At 390px, the SIMULATION ONLY notice and the freshness indicator are removed by CSS. Four routes scroll sideways, 9 of 12 nav items are hidden off-screen, and the Upcoming table clips the predictions themselves. The disclaimer is an integrity issue that takes minutes to fix. The rest makes the product usable on the device most football fans use.
3. **UX-3 + UX-7: organise by task and show the evidence first.** Twelve nav items split by engine force users to learn the architecture before they can find a match. Meanwhile, the performance pages lead with rows of €0.00 and "—", and one page links to Engine B validation that does not exist. Four task-based sections, with track-record pages that open on the walk-forward evidence and state plainly when live data is still empty, make the product easier to understand and more credible.
