# Agent 9 cross-review of Agent 10 (DevOps) and Agent 5 (Providers)

## Agreements, with independent verification
- **No scheduled run has happened yet.** OP-1 is consistent with my own check: `event=schedule` returned `total_count 0` at about 01:50 UTC.
- **The manifest and database upload is not atomic.** OP-5 matches QA-4, and both of us saw the same timestamps (00:28:10 and 00:28:11).
- **The backup health signal is misleading.** OP-6 matches QA-15.
- **Backups are not independent.** OP-7 and OP-10 match QA-9. All copies live in a single repository.
- **Alerting** (OP-4) matches QA-10. Agent 10 adds one important fact: failure e-mails go to whoever last edited the cron line, and that was a `noreply` identity.
- **Odds API errors are hidden (DP-3).** I verified this at `collect.py:121-125`: `mark_error` is followed unconditionally by `mark_success`. It is worse than a hidden error. `mark_success` resets `circuit.failures` to 0 (`base.py:96-98`), so **the circuit breaker can never open for the Odds API**.
- **The live adapter skips the provider layer** (`live.py`: raw `httpx`, and `remaining` is discarded). I verified this. It also escapes the `Provider.get` 429 handling that I reviewed. DP-3 is correct.
- **Live freshness is always reported as current.** I verified `provider_updated_at=now` at `live.py:175`.

## Disagreements and wrong statuses or priorities
1. **OP-2 and OP-3 should be P1, not P0.**
   - A cancelled run, or a wasted live run, delays settlement by at most one cycle. Every job is idempotent and the next run catches up.
   - Neither causes a loss of integrity. In the council's scheme, P0 means critical to reliability, security or integrity.
   - One argument does support them: each live run is one more non-atomic database upload, about 39 a day. That strengthens OP-2 as a way to reduce risk, but it remains P1.
2. **Agent 10 calls the safety design "solid" but misses two failure paths:**
   - Every step uses `if: always()`, so a failed restore or export still runs `export_static`. That calls `init_db()` on an empty database and `git push -f` publishes an empty dashboard (QA-3).
   - The `fil integrity` command in the restore step re-creates missing triggers before it checks for them (QA-2).
   Only `fil guard` inspects the raw file, so "the guard checks the triggers" is true, but the restore-step check is not.
3. **DP-4 has the wrong status.** It should be MISSING, not IMPLEMENTED BUT NEEDS VERIFICATION. Agent 5's own evidence, and the code at `live.py:175`, show the fix has not been made.
4. **DP-1 should be P1 now, and a hard gate before any key is added.** No key is configured, so it cannot exhaust a quota today. Its acceptance criteria should also require that a 429 or a quota stop does not reset the circuit breaker (see the DP-3 finding above).
5. **`queue: max` in OP-3 needs checking.** I could not verify this concurrency key against the documentation. Before relying on it, test it on a throwaway workflow. Staggering the cron minutes works without it.

## Changes to my own recommendations
- **QA-9:** lowered from P1 to P2 and merged with OP-7 and OP-10. A weekly automated restore drill plus a monthly copy kept off GitHub by the owner is enough. Neither needs new infrastructure.
- **QA-5:** add that a run reporting `skipped` because a stale lease blocked it must be visible in the run summary. OP-2 shrinks the chance of this by cutting the number of runs.
- **QA-10:** adopt Agent 10's method, opening a GitHub issue on failure plus a one-time cron edit by the owner, as the acceptance path.
- **New, QA-16 (P1, XS):** add tests showing that a provider error inside a run is not overwritten by `mark_success`, and that the circuit breaker opens after three failing runs. The test should cover both the Odds API path and the API-Football live path. This depends on DP-3.
- **QA-14 (Retry-After/body validation):** now applies to the live adapter as well, once DP-3 routes it through `Provider.get`.
- **Top 3 unchanged:** QA-1+2, then QA-3+4+5, then QA-10. OP-5 should be implemented together with QA-4, as a single change.
