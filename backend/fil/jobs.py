"""Job definitions + a safe runner (records every run, never overlaps, never crashes the app)."""
from __future__ import annotations

import threading
import traceback

from sqlalchemy import select

from . import backup, collect, coverage, pipeline, reports
from .betting import settle_pending
from .db import JobRun, log, session_scope
from .timeutil import utcnow

_LOCK = threading.Lock()


def job_fixtures_odds() -> dict:
    out = {"collect": collect.collect_fixtures()}
    out["predict"] = pipeline.predict_upcoming()
    return out


def job_results() -> dict:
    out = {"collect": collect.collect_history(full=False)}
    out["settle"] = settle_pending()
    out["evaluate"] = pipeline.evaluate_predictions()
    return out


def job_prematch_review() -> dict:
    return {"predict": pipeline.predict_upcoming()}


def job_daily() -> dict:
    out = {}
    out["results"] = collect.collect_history(full=False)
    out["fixtures"] = collect.collect_fixtures()
    out["international"] = collect.collect_international()
    out["settle"] = settle_pending()
    out["evaluate"] = pipeline.evaluate_predictions()
    eng = pipeline.get_engine(force=True)
    out["predict"] = pipeline.predict_upcoming(eng)
    out["coverage"] = len(coverage.assess_coverage(eng))
    out["report"] = reports.daily_report()
    out["backup"] = str(backup.backup().name)
    return out


def job_weekly() -> dict:
    from .backtest import run_backtest

    bt = run_backtest()
    return {"weekly_report": reports.weekly_report(), "backtest": bt["metrics"].get("ensemble"), "strategy": bt["strategy"]}


def job_bootstrap() -> dict:
    """First-run initialisation: full history import, then the daily cycle."""
    collect.register_all()
    out = {"history": collect.collect_history(full=True)}
    out["daily"] = job_daily()
    return out


JOBS = {
    "bootstrap": job_bootstrap,
    "daily": job_daily,
    "fixtures_odds": job_fixtures_odds,
    "results": job_results,
    "prematch_review": job_prematch_review,
    "weekly": job_weekly,
    "backup": lambda: {"file": str(backup.backup())},
}


def run_job(name: str) -> dict:
    if name not in JOBS:
        raise KeyError(name)
    if not _LOCK.acquire(blocking=False):
        log("INFO", "scheduler", f"job {name} skipped: another job is running")
        with session_scope() as s:
            s.add(JobRun(job=name, status="skipped", finished_at=utcnow(), summary={"reason": "another job running"}))
        return {"skipped": True}
    with session_scope() as s:
        run = JobRun(job=name, status="running")
        s.add(run)
        s.flush()
        run_id = run.id
    try:
        summary = JOBS[name]()
        status, err = "success", None
    except Exception as exc:  # recorded and surfaced on the System Health page
        summary, status, err = None, "error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-3000:]}"
        log("ERROR", f"job.{name}", f"{type(exc).__name__}: {exc}")
    finally:
        _LOCK.release()
    with session_scope() as s:
        run = s.get(JobRun, run_id)
        run.finished_at, run.status, run.error = utcnow(), status, err
        run.summary = _jsonable(summary)
    return {"status": status, "summary": summary, "error": err}


def _jsonable(x):
    import json

    return json.loads(json.dumps(x, default=str)) if x is not None else None


def last_success(name: str):
    with session_scope() as s:
        r = s.scalars(select(JobRun).where(JobRun.job == name, JobRun.status == "success")
                      .order_by(JobRun.finished_at.desc())).first()
        return r.finished_at if r else None


def recover_stale_runs() -> None:
    """Runs left 'running' by a crash/restart are marked interrupted."""
    with session_scope() as s:
        for r in s.scalars(select(JobRun).where(JobRun.status == "running")):
            r.status, r.finished_at, r.error = "interrupted", utcnow(), "process restarted before completion"
