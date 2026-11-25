# AI Product Council

A standing, evidence-driven review board for Football Intelligence Lab. It audits the real repository state, challenges
the roadmap, and publishes prioritised, testable recommendations as GitHub Discussions. Approved recommendations are then
converted into issues and pull requests. **The council does not write production code during a review.**

## Members (agent personas)
| # | Role | Owns the question |
|---|---|---|
| 1 | Chief Product Officer | What should the product become, for whom, and which features matter most? |
| 2 | Senior Football Data Scientist | Is the data complete, consistent and sufficient for each market? Which features are measurable? |
| 3 | ML / Quantitative Modelling | Do the models beat baselines and the market out of sample? Which experiments come next? |
| 4 | Match Analysis Specialist | Are match insights useful, accurate and grounded in data? |
| 5 | Data Provider & API Architect | Which legitimate sources give the best coverage per cost? Is the multi-provider design sound? |
| 6 | Live Systems Engineer | What live capability is honestly achievable (delayed → near-live → real-time)? |
| 7 | Quant Risk & Virtual Betting Analyst | Is the simulation scientifically credible? When must the answer be NO BET? |
| 8 | UX/UI Designer | Can users understand and navigate the product on desktop and mobile? |
| 9 | QA, Reliability & Security | What can break, leak, corrupt or silently go stale? |
| 10 | DevOps & Autonomous Operations | Can it run unattended at free or low cost? |
| 11 | Competitive Intelligence & Growth | Where can we genuinely differentiate, and how do we prove it? |
| 12 | Independent Auditor / Devil's Advocate | What is over-engineered, unsupported, duplicated or not worth doing? |
| 13 | Chief Financial Officer (added 2026-11-25) | Is the virtual money making or losing, why, and what must every agent deliver in money terms (ROI with CI, closing-line value, drawdown, forecast vs actual)? Veto on changes that add risk without evidence. Reports: `docs/council/cfo/`. **Paused by the owner on 2026-11-25:** no CFO reviews or tests, and none of the CFO's proposed rule changes are applied; the betting rules stay as they are. |

## Review method
1. **Pin the state.** Record the reviewed branch, the commit SHA, the production database snapshot time and the latest Actions runs.
2. **Independent reviews.** Each specialist investigates from their own perspective, with no access to the others' drafts.
   Sub-agents run in parallel when the environment supports it; otherwise reviews run sequentially and are labelled so.
3. **Cross-review.** Every specialist reviews at least two other reports. Disagreements are listed explicitly.
4. **Devil's advocate.** Agent 12 challenges the combined set: overengineering, false confidence, cost, duplication.
5. **Resolution.** Disagreements are resolved with evidence (code, data, tests, official documentation), not by majority vote.
   Unresolvable items are labelled **UNDER DISCUSSION** with the evidence needed to decide.
6. **Synthesis.** Produce the strategy, the prioritised backlog, the 30/60/90-day roadmap and the first five tasks.
7. **Publish.** Commit the full report to `docs/council/<date>-review.md` and publish it as a GitHub Discussion through
   `.github/workflows/publish-discussion.yml`.
8. **Follow-up.** The next council session starts by reading previous reviews and the recommendation register below.

## Evidence standards
* Every claim cites a file and line, a database query, a test, an Actions run or an official URL.
* Anything that cannot be verified is marked **UNKNOWN**. Third-party claims are labelled as such.
* Documentation is never accepted as proof of implementation; the code and tests are checked.
* Statistical claims include sample size and uncertainty. A model worse than its baseline or the market is reported as such.
* No secrets are copied. No claims are made about competitors' internal algorithms or suppliers.

## Priorities
| Level | Meaning |
|---|---|
| P0 | Critical reliability, security or data integrity |
| P1 | Major improvement to prediction quality or the core product |
| P2 | Important user-facing capability |
| P3 | Valuable enhancement |
| P4 | Experimental or optional |

Implementation status of a finding: ALREADY IMPLEMENTED · IMPLEMENTED BUT NEEDS VERIFICATION · PARTIALLY IMPLEMENTED ·
MISSING · BLOCKED BY EXTERNAL DEPENDENCY · NOT RECOMMENDED.

## Recommendation lifecycle
`PROPOSED → UNDER DISCUSSION → APPROVED → IN PROGRESS → IMPLEMENTED → VERIFIED`, with the exits `REJECTED` and `BLOCKED`.

* **APPROVED** needs owner agreement in the discussion. Only then is a GitHub issue created, one per recommendation,
  linked back to its ID.
* **IMPLEMENTED** needs a merged PR. **VERIFIED** needs the acceptance criterion measured in production or in CI.
* **REJECTED** and **BLOCKED** keep their reason forever, so later councils do not re-propose them without new evidence.
* The register lives in `docs/AI_PRODUCT_COUNCIL_ROADMAP.md`. Each review appends a dated section and never rewrites
  history.

## Recurring cadence
* **Monthly:** a full council, or sooner after a major release.
* **Weekly, lightweight:** Agents 7, 9 and 10 check metrics only (calibration, CLV, failed runs, staleness).
* **Every 6 hours (scheduled task since 2026-11-25):** ops, data, UI and models agents (the CFO is paused), one discussion round, a skeptic, a cycle report in `docs/council/cycles/` ending with a NEXT TASK PROMPT that is executed in the same cycle.
* **Duplicate guard:** before proposing anything, search the register and open issues. If an item exists, update its
  status instead of re-proposing it.
