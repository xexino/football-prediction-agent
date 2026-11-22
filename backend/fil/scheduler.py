"""In-process scheduler (APScheduler). Schedules are in Europe/Rome time.

On start-up it marks interrupted runs, bootstraps an empty database, and catches up on a
missed daily cycle — so restarting the container/app resumes safely.
"""
from __future__ import annotations

import threading
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select

from .db import Fixture, log, session_scope
from .jobs import last_success, recover_stale_runs, run_job
from .timeutil import utcnow

TZ = "Europe/Rome"
SCHEDULE = {
    "daily": CronTrigger(hour=6, minute=10, timezone=TZ),
    "fixtures_odds": IntervalTrigger(hours=3, timezone=TZ),
    "results": IntervalTrigger(hours=6, timezone=TZ),
    "prematch_review": IntervalTrigger(minutes=60, timezone=TZ),
    "weekly": CronTrigger(day_of_week="mon", hour=7, minute=20, timezone=TZ),
}
DESCRIPTIONS = {
    "daily": "Full cycle: results → fixtures/odds → settle → retrain → predict → coverage → report → backup",
    "fixtures_odds": "Discover fixtures & refresh odds, then re-run predictions (revisions recorded separately)",
    "results": "Fetch results, verify, settle virtual bets, evaluate predictions",
    "prematch_review": "Pre-match review of upcoming fixtures (new revision only on material change)",
    "weekly": "Weekly performance report + walk-forward backtest",
}

_sched: BackgroundScheduler | None = None


def start() -> BackgroundScheduler:
    global _sched
    if _sched is not None:
        return _sched
    recover_stale_runs()
    _sched = BackgroundScheduler(timezone=TZ, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    for name, trig in SCHEDULE.items():
        _sched.add_job(run_job, trig, args=[name], id=name, name=name, replace_existing=True)
    _sched.start()
    log("INFO", "scheduler", "scheduler started")
    threading.Thread(target=_catch_up, daemon=True).start()
    return _sched


def _catch_up() -> None:
    with session_scope() as s:
        n = s.scalar(select(func.count(Fixture.id)))
    if n < 1000:
        log("INFO", "scheduler", "empty database: running bootstrap")
        run_job("bootstrap")
        return
    last = last_success("daily")
    if last is None or utcnow() - last > timedelta(hours=24):
        log("INFO", "scheduler", "daily cycle missed: catching up")
        run_job("daily")


def status() -> list[dict]:
    out = []
    for name in SCHEDULE:
        job = _sched.get_job(name) if _sched else None
        nxt = job.next_run_time if job else None
        out.append({"job": name, "description": DESCRIPTIONS[name], "trigger": str(SCHEDULE[name]),
                    "next_run": nxt.isoformat() if nxt else None, "last_success": last_success(name)})
    return out


def running() -> bool:
    return bool(_sched and _sched.running)


def shutdown() -> None:
    global _sched
    if _sched:
        _sched.shutdown(wait=False)
        _sched = None
