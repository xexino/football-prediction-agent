"""Reliable Autopilot timer (stdlib only).

GitHub's own `schedule:` trigger is best effort: on 23–25 Nov 2026 it started only 9 of ~16 critical slots and
almost no live slots, some of them 10 h late. This dispatcher runs inside a long-lived workflow
(.github/workflows/dispatcher.yml), wakes every minute, and starts the Autopilot job of every slot in
fil/ops/schedule.py SCHEDULES with `workflow_dispatch`, which GitHub executes immediately. Before ~6 h (the job
limit) it starts its own successor. The GitHub cron triggers stay as a fallback; a duplicate run is harmless
because every job is idempotent, and the dispatcher skips a slot that a cron-triggered run already covers.

    python backend/fil/ops/dispatcher.py --repo OWNER/REPO --max-minutes 345
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .schedule import SCHEDULES, matches
except ImportError:  # executed as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from fil.ops.schedule import SCHEDULES, matches  # type: ignore

DEDUP_MIN = 15  # a run for the same job started within 15 min before the slot (or after it) covers the slot
# The watchdog must be started by the dispatcher: runs dispatched with GITHUB_TOKEN never fire `workflow_run`, and
# GitHub's cron for this repository is unreliable (council cycle 2026-11-25 12:51: no watchdog run after 09:08).
WATCHDOG_MINUTES = (17, 50)  # hourly, and 10 min after every :40 critical slot


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)


def due(minute: datetime) -> list[tuple[str, str]]:
    """(cron, job) pairs due at this minute; when several fall on one minute only the broadest job runs."""
    out = [(c, v[0]) for c, v in SCHEDULES.items() if matches(c, minute)]
    jobs = {j for _, j in out}
    if "daily" in jobs:  # daily already includes results + fixtures/odds + live polling
        out = [(c, j) for c, j in out if j in ("daily", "weekly")]
    return out


def covered(runs: list[dict], cron: str, job: str, slot: datetime) -> bool:
    for r in runs:
        title = r.get("display_title") or ""
        created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        if created < slot - timedelta(minutes=DEDUP_MIN):
            continue
        if cron in title or title.endswith(f"· {job}"):
            return True
    return False


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def recent_runs(repo: str) -> list[dict]:
    return json.loads(gh("api", f"repos/{repo}/actions/workflows/autopilot.yml/runs?per_page=30"))["workflow_runs"]


def dispatch(repo: str, workflow: str, job: str | None = None) -> bool:
    args = ["workflow", "run", workflow, "--repo", repo, "--ref", "main"]
    if job:
        args += ["-f", f"job={job}"]
    for attempt in range(3):
        try:
            gh(*args)
            return True
        except Exception as exc:  # transient API failure: bounded retry, then report
            print(f"::warning::dispatch {workflow} {job or ''} failed (attempt {attempt + 1}): {exc}", flush=True)
            time.sleep(10 * (attempt + 1))
    print(f"::error::could not dispatch {workflow} {job or ''}", flush=True)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--max-minutes", type=int, default=345)
    a = ap.parse_args(argv)
    start = now_utc()
    last = start - timedelta(minutes=1)
    while True:
        cur = now_utc()
        if cur - start >= timedelta(minutes=a.max_minutes):
            print("handing over to a new dispatcher run", flush=True)
            ok = dispatch(a.repo, "dispatcher.yml")
            # a broken hand-over must be loud: the watchdog (started below every hour) restarts the chain, and a
            # failed dispatcher run is visible in Actions
            return 0 if ok else 1
        m = last + timedelta(minutes=1)
        while m <= cur:  # also processes minutes missed while a dispatch was slow
            if m.minute in WATCHDOG_MINUTES and (m.minute == 17 or m.hour % 3 == 0):
                dispatch(a.repo, "watchdog.yml")
            for cron, job in due(m):
                try:
                    runs = recent_runs(a.repo)
                except Exception as exc:
                    print(f"::warning::cannot read runs ({exc}); dispatching anyway", flush=True)
                    runs = []
                if covered(runs, cron, job, m):
                    print(f"{m:%H:%M} {job}: already started by another trigger", flush=True)
                else:
                    print(f"{m:%H:%M} {job}: dispatching", flush=True)
                    dispatch(a.repo, "autopilot.yml", job)
            m += timedelta(minutes=1)
        last = cur
        time.sleep(max(5, 60 - datetime.now(timezone.utc).second))




# --------------------------------------------------------------------------- duplicate gate for late cron runs
GATE_WINDOW = {"daily": timedelta(hours=20), "weekly": timedelta(days=6),
               "results,fixtures_odds": timedelta(minutes=150), "live": timedelta(minutes=15)}


def is_duplicate(runs: list[dict], job: str, this_run_id: int, now: datetime) -> bool:
    """A cron-triggered run is redundant if the same job already started (and did not fail) within its window —
    typically because the dispatcher ran the slot on time and GitHub delivered the cron event hours late."""
    win = GATE_WINDOW.get(job)
    if not win:
        return False
    for r in runs:
        if r.get("id") == this_run_id:
            continue
        created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        title = r.get("display_title") or ""
        same = title.endswith(f"· {job}") or any(c in title for c, v in SCHEDULES.items() if v[0] == job)
        if same and now - created < win and r.get("conclusion") in (None, "success"):
            return True
    return False


def gate_main(argv=None) -> int:
    """`python dispatcher.py gate --repo R --event E --job J --run-id N` prints run=true|false."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--event", required=True)
    ap.add_argument("--job", default="")
    ap.add_argument("--run-id", type=int, required=True)
    a = ap.parse_args(argv)
    run = True
    if a.event == "schedule":
        try:
            run = not is_duplicate(recent_runs(a.repo), a.job, a.run_id, now_utc())
        except Exception as exc:  # if GitHub cannot be asked, do the work (duplicates are harmless)
            print(f"::warning::duplicate check failed: {exc}", file=sys.stderr)
    print(f"run={'true' if run else 'false'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gate":
        sys.exit(gate_main(sys.argv[2:]))
    sys.exit(main())
