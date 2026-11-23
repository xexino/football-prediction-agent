"""Operational status of the Autopilot run that is publishing the dashboard (stdlib only).

The workflow calls this after every run — including failed ones — so the dashboard can show what actually
happened (which stage failed, whether the database was persisted, whether the data shown is a partial or a
previous snapshot) instead of a stale "healthy" page.

    python -m fil.ops.status --site site --prev prev_site/data/ops_history.json

Inputs come from environment variables set by the workflow (OPS_*). Nothing secret is read or written.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HISTORY_KEEP = 300
STAGES = ("restore", "route", "run", "persist", "export")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(env: dict, history: list[dict], now: str | None = None) -> tuple[dict, list[dict]]:
    now = now or _now()
    restore = env.get("OPS_RESTORE", "skipped")          # success | failure | skipped
    route_ok = env.get("OPS_ROUTE", "skipped")            # success | failure | skipped
    job_status = env.get("OPS_JOB_STATUS") or "none"      # success | partial | error | skipped | none
    persist = env.get("OPS_PERSIST") or "skipped"         # persisted | unchanged | refused | failed | skipped
    if env.get("OPS_PERSIST_STEP") == "failure" and persist not in ("refused", "failed"):
        persist = "failed"  # the step failed before it could record a more specific reason
    export = env.get("OPS_EXPORT", "skipped")             # success | failure | skipped

    stage_state = {
        "restore": "ok" if restore == "success" else "failed",
        "route": "ok" if route_ok == "success" else ("failed" if restore == "success" else "not_run"),
        "run": {"success": "ok", "partial": "partial", "skipped": "skipped"}.get(job_status,
                                                                                 "failed" if route_ok == "success" else "not_run"),
        "persist": {"persisted": "ok", "unchanged": "ok"}.get(persist, "failed" if persist in ("refused", "failed") else "not_run"),
        "export": "ok" if export == "success" else ("failed" if export == "failure" else "not_run"),
    }
    failure_stage = next((st for st in STAGES if stage_state[st] == "failed"), None)
    if failure_stage:
        state = "FAILED"
    elif stage_state["run"] in ("partial", "skipped") or stage_state["persist"] == "not_run":
        state = "DEGRADED"
    else:
        state = "HEALTHY"
    rec = {
        "run_id": env.get("OPS_RUN_ID"), "run_attempt": env.get("OPS_RUN_ATTEMPT"), "run_url": env.get("OPS_RUN_URL"),
        "event": env.get("OPS_EVENT"), "schedule": env.get("OPS_SCHEDULE") or None, "job": env.get("OPS_JOB") or None,
        "commit": (env.get("OPS_SHA") or "")[:12] or None, "started_at": env.get("OPS_STARTED_AT"), "finished_at": now,
        "state": state, "failure_stage": failure_stage, "stages": stage_state, "job_status": job_status,
        "database": {"restore": restore, "source": env.get("OPS_RESTORE_SOURCE") or None, "persist": persist,
                     "persist_detail": env.get("OPS_PERSIST_DETAIL") or None},
        # the dashboard data in this publication comes from this run only if the export succeeded
        "dashboard_data": "fresh" if export == "success" else "previous_snapshot",
        "partial": job_status == "partial" or export != "success",
    }
    history = ([h for h in history if h.get("run_id") != rec["run_id"]] + [rec])[-HISTORY_KEEP:]
    last_ok = next((h for h in reversed(history) if h["state"] == "HEALTHY"), None)
    last_bad = next((h for h in reversed(history) if h["state"] == "FAILED"), None)
    consecutive = 0
    for h in reversed(history):
        if h["state"] != "FAILED":
            break
        consecutive += 1
    status = {
        "generated_at": now, "current": rec,
        "last_success_at": last_ok["finished_at"] if last_ok else None,
        "last_failure_at": last_bad["finished_at"] if last_bad else None,
        "last_failure_stage": last_bad["failure_stage"] if last_bad else None,
        "consecutive_failures": consecutive,
        "recent": [{k: h.get(k) for k in ("run_id", "job", "event", "state", "failure_stage", "finished_at", "run_url")}
                   for h in history[-20:]][::-1],
        "notes": ("Pipeline state of the run that published this page. The dashboard additionally marks data "
                  "older than 8 h as STALE; GitHub can delay or skip scheduled runs, which the separate "
                  "watchdog workflow reports as GitHub issues labelled 'autopilot-incident'."),
    }
    return status, history


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, help="dashboard directory about to be published")
    ap.add_argument("--prev", help="previous ops_history.json (from the currently published gh-pages)")
    a = ap.parse_args(argv)
    history = []
    if a.prev and Path(a.prev).exists():
        try:
            history = json.loads(Path(a.prev).read_text())
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []  # a damaged history file must not block publishing the current status
    status, history = build(dict(os.environ), history)
    data = Path(a.site) / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "ops_status.json").write_text(json.dumps(status, indent=1))
    (data / "ops_history.json").write_text(json.dumps(history))
    print(f"ops state {status['current']['state']} (failure stage: {status['current']['failure_stage'] or '—'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
