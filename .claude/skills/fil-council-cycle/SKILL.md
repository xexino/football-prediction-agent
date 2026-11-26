---
name: fil-council-cycle
description: Run one AI Product Council cycle for Football Intelligence Lab — gather state, convene the ops / data / UI / models agents in parallel, a skeptic challenge, a dated cycle report with a NEXT TASK PROMPT, then implement, test, merge, republish and verify. Use when the 6-hourly scheduled council fires, or when asked to "run the council", review the app end to end, or find and fix what is wrong.
---

# AI Product Council cycle

Follow `fil-guardrails` throughout. The CFO is paused (no CFO work, no betting-rule proposals).

## 1. State (≈5 min)
- `git fetch`, reset to `origin/main`, note the SHA.
- Run history via `gh api` (GET): `autopilot.yml`, `dispatcher.yml`, `watchdog.yml`; open `autopilot-incident` issues.
- Download the live `data/{ops_status,health_detail,engine_compare,overview}.json` and the `db-latest` release DB
  (`fil.db.gz`) into a new scratch dir; open the DB read-only (`sqlite3` URI `mode=ro`).
- Read the latest `docs/council/cycles/*.md` and `docs/AI_PRODUCT_COUNCIL_ROADMAP.md` — never redo finished work, and
  re-check anything the last cycle said it would verify.

## 2. Meeting (parallel, read-only sub-agents)
Brief each agent with the snapshot paths, what changed last cycle and what is deferred.
- **Ops/reliability:** slots vs runs (`backend/fil/ops/schedule.py`), dispatcher hand-overs, gate skips, provider
  errors/429s with timestamps from job logs, step durations (`job_runs`), overdue results.
- **Data & results:** web-verify a sample of new results (search snippets; no forbidden scraping), conflicts,
  duplicates, ledgers of both engines, prediction coverage.
- **UI/console:** Playwright crawl of every route (desktop 1366×900 + iPhone 13), console/network errors, numbers vs the
  JSON, clock-shifted checks for match states (`lib/matchState.ts` is the single rule).
- **Models:** live LL/Brier/favourite-hit for A, B, market, naive on identical matches with CIs; the next pre-registered
  walk-forward idea, or an honest "none".
Then a **skeptic** agent challenges the combined list (and later the actual diff): AGREE / CHANGE / REJECT per item.

## 3. Report
`docs/council/cycles/<YYYY-MM-DD-HHMM>-cycle.md` (≤ ~1,000 words): status, findings table with evidence, rulings,
and a **NEXT TASK PROMPT** (top 1–3 fixes with acceptance tests). Append dated lines to the roadmap register
(IN PROGRESS / IMPLEMENTED / VERIFIED / REJECTED / DEFERRED + reason). Correct earlier claims that turned out wrong.

## 4. Act
Branch `cycle/<date>-<HHMM>` off main → implement → tests that fail on the old code → the four gates in
`fil-guardrails` → PR → CI green → merge → dispatch `autopilot.yml` (`results,fixtures_odds`) → verify in production
(job logs, `job_runs`, live JSON, Playwright). If the verification reveals a bug, fix it in a follow-up PR the same cycle.

## 5. Message to the owner
Plain language, short: what the council found, what was fixed (PR links), what is still open, what is next.
If nothing important is found, say so and change nothing.
