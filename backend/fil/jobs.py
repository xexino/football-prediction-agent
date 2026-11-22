"""Job definitions + a safe runner.

* Each job is a list of independent STEPS. A failing step is recorded and the remaining steps still
  run (e.g. a provider outage must not stop settlement or predictions on existing data).
* Steps marked critical (settlement, prediction) decide whether a run is FAILED; otherwise a run
  with failed steps is PARTIAL.
* Every run stores a structured report (steps, durations, counts, errors) in job_runs.summary.
* Runs never overlap (in-process lock + database lease for multi-process safety).
"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import timedelta

from sqlalchemy import select

from . import backup, collect, coverage, pipeline, reports
from .betting import settle_pending
from .db import JobRun, log, session_scope
from .timeutil import utcnow

_LOCK = threading.Lock()
LEASE_MINUTES = 90  # a 'running' row older than this is considered dead (crashed process)

# (step name, callable, critical?)
def _steps_results():
    return [("results", lambda: collect.collect_history(full=False), False),
            ("settle", settle_pending, True),
            ("evaluate", pipeline.evaluate_predictions, False)]


def _steps_fixtures():
    return [("fixtures", collect.collect_fixtures, False),
            ("predict", lambda: pipeline.predict_upcoming(), True)]


def _steps_daily():
    return [
        ("results", lambda: collect.collect_history(full=False), False),
        ("fixtures", collect.collect_fixtures, False),
        ("international", collect.collect_international, False),
        ("settle", settle_pending, True),
        ("evaluate", pipeline.evaluate_predictions, False),
        ("retrain", lambda: _retrain(), False),
        ("predict", lambda: pipeline.predict_upcoming(), True),
        ("coverage", lambda: len(coverage.assess_coverage(pipeline.get_engine())), False),
        ("integrity", lambda: _integrity(), True),
        ("report", reports.daily_report, False),
        ("backup", lambda: str(backup.backup(verify=True).name), False),
    ]


def _steps_weekly():
    from .backtest import run_backtest

    def bt():
        r = run_backtest()
        return {"ensemble": r["metrics"].get("ensemble"), "strategy": r["strategy"]}
    return [("backtest", bt, False), ("weekly_report", reports.weekly_report, False)]


def _steps_bootstrap():
    return [("register", collect.register_all, True),
            ("history", lambda: collect.collect_history(full=True), True)] + _steps_daily()


def _retrain():
    e = pipeline.get_engine(force=True)
    return {"competitions_fitted": len(e.dc)}


def _integrity():
    from .integrity import check_database

    res = check_database()
    if not res["ok"]:
        raise RuntimeError(f"integrity check failed: {res['problems']}")
    return res


JOBS = {
    "bootstrap": _steps_bootstrap,
    "daily": _steps_daily,
    "fixtures_odds": _steps_fixtures,
    "results": _steps_results,
    "prematch_review": lambda: [("predict", lambda: pipeline.predict_upcoming(), True)],
    "weekly": _steps_weekly,
    "backup": lambda: [("backup", lambda: str(backup.backup(verify=True)), True)],
}


def _acquire_lease(name: str) -> int | None:
    """Database lease so two processes (e.g. server + CLI) never run jobs concurrently."""
    with session_scope() as s:
        cutoff = utcnow() - timedelta(minutes=LEASE_MINUTES)
        live = s.scalars(select(JobRun).where(JobRun.status == "running", JobRun.started_at > cutoff)).first()
        if live is not None:
            s.add(JobRun(job=name, status="skipped", finished_at=utcnow(),
                         summary={"reason": f"job '{live.job}' (#{live.id}) still running"}))
            return None
        run = JobRun(job=name, status="running")
        s.add(run)
        s.flush()
        return run.id


def run_job(name: str, timeout_s: int | None = None) -> dict:
    """Run a job's steps. Returns {"status": success|partial|error|skipped, "summary": ..., "error": ...}."""
    if name not in JOBS:
        raise KeyError(name)
    if not _LOCK.acquire(blocking=False):
        log("INFO", "scheduler", f"job {name} skipped: another job is running")
        with session_scope() as s:
            s.add(JobRun(job=name, status="skipped", finished_at=utcnow(), summary={"reason": "another job running"}))
        return {"skipped": True, "status": "skipped"}
    try:
        run_id = _acquire_lease(name)
        if run_id is None:
            return {"skipped": True, "status": "skipped"}
        started = time.time()
        steps, results, errors = {}, {}, []
        try:
            step_list = JOBS[name]()
        except Exception as exc:  # building the step list failed (import error etc.)
            step_list = []
            errors.append(f"setup: {type(exc).__name__}: {exc}")
        critical_failed = False
        for sname, fn, critical in step_list:
            if timeout_s and time.time() - started > timeout_s:
                steps[sname] = {"status": "skipped", "reason": "job timeout reached"}
                continue
            t0 = time.time()
            try:
                res = fn()
                steps[sname] = {"status": "success", "duration_s": round(time.time() - t0, 1)}
                results[sname] = res
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                steps[sname] = {"status": "error", "duration_s": round(time.time() - t0, 1), "critical": critical,
                                "error": msg[:600]}
                errors.append(f"{sname}: {msg}\n{traceback.format_exc()[-1500:]}")
                log("ERROR", f"job.{name}.{sname}", msg)
                critical_failed = critical_failed or critical
        failed = [k for k, v in steps.items() if v["status"] == "error"]
        if errors and (critical_failed or not step_list or len(failed) == len(step_list)):
            status = "error"
        elif errors:
            status = "partial"
        else:
            status = "success"
        summary = {"steps": steps, "results": results, "report": run_report(name, steps, results, status)}
        err = "\n\n".join(errors)[-6000:] if errors else None
        with session_scope() as s:
            run = s.get(JobRun, run_id)
            run.finished_at, run.status, run.error = utcnow(), status, err
            run.summary = _jsonable(summary)
        return {"status": status, "summary": summary, "error": err}
    finally:
        _LOCK.release()


def run_report(name: str, steps: dict, results: dict, status: str) -> dict:
    """Concise operational report for one run (shown on System Health and in the Actions summary)."""
    fx = results.get("fixtures") or {}
    fdu = fx.get("football_data_uk", {}) if isinstance(fx, dict) else {}
    pred = results.get("predict") or {}
    settle = results.get("settle") or {}
    res = results.get("results") or {}
    provider_failures = []
    if isinstance(fx, dict):
        for k, v in fx.items():
            if isinstance(v, dict) and (v.get("error") or v.get("errors")):
                provider_failures.append(k)
    if isinstance(res, dict) and res.get("errors"):
        provider_failures.append("football_data_uk:results")
    return {
        "job": name, "status": status,
        "fixtures_discovered": fdu.get("fixtures_new", 0) if isinstance(fdu, dict) else 0,
        "fixtures_updated": (fdu.get("fixtures_dup", 0) + fdu.get("kickoff_changes", 0)) if isinstance(fdu, dict) else 0,
        "duplicates_merged": fx.get("merged_duplicates", 0) if isinstance(fx, dict) else 0,
        "predictions_generated": pred.get("predicted", 0) + pred.get("revisions", 0),
        "predictions_skipped": pred.get("ineligible", 0) + pred.get("unchanged", 0),
        "virtual_bets_created": pred.get("bets", 0),
        "no_bet_decisions": pred.get("no_bet", 0),
        "bets_settled": settle.get("settled", 0) + settle.get("voided", 0),
        "bets_pending_conflict": settle.get("conflicts", 0),
        "provider_failures": provider_failures,
        "failed_steps": [k for k, v in steps.items() if v.get("status") == "error"],
        "database_persisted": None,  # filled by the workflow (persist step) when applicable
    }


def report_markdown(run: JobRun) -> str:
    rep = (run.summary or {}).get("report") or {}
    steps = (run.summary or {}).get("steps") or {}
    lines = [f"### Run #{run.id} `{run.job}` — **{run.status.upper()}**", "",
             "| Step | Status | Duration |", "|---|---|---|"]
    for k, v in steps.items():
        lines.append(f"| {k} | {v.get('status')} | {v.get('duration_s', '—')}s |")
    lines += ["", "| Metric | Value |", "|---|---|"]
    for k, v in rep.items():
        if k not in ("job", "status"):
            lines.append(f"| {k.replace('_', ' ')} | {v if v not in (None, []) else '—'} |")
    if run.error:
        lines += ["", "```", run.error[:1500], "```"]
    return "\n".join(lines)


def _jsonable(x):
    import json

    return json.loads(json.dumps(x, default=str)) if x is not None else None


def last_success(name: str):
    with session_scope() as s:
        r = s.scalars(select(JobRun).where(JobRun.job == name, JobRun.status.in_(["success", "partial"]))
                      .order_by(JobRun.finished_at.desc())).first()
        return r.finished_at if r else None


def last_step_success(step: str):
    """Most recent time a given step succeeded in any job."""
    with session_scope() as s:
        for r in s.scalars(select(JobRun).where(JobRun.finished_at.is_not(None)).order_by(JobRun.id.desc()).limit(200)):
            st = ((r.summary or {}).get("steps") or {}).get(step)
            if st and st.get("status") == "success":
                return r.finished_at
            if r.summary and step in (r.summary or {}) and r.status == "success":  # legacy (pre-step) runs
                return r.finished_at
    return None


def recover_stale_runs() -> None:
    """Runs left 'running' by a crash/restart are marked interrupted."""
    with session_scope() as s:
        for r in s.scalars(select(JobRun).where(JobRun.status == "running")):
            r.status, r.finished_at, r.error = "interrupted", utcnow(), "process restarted before completion"
