"""Autopilot watchdog: judges the *GitHub Actions run history* (not the Autopilot's own report), so it can
detect runs that failed, hung, were cancelled, or never started at all.

Stdlib only. Usage (from the repository root, see .github/workflows/watchdog.yml):

    python backend/fil/ops/watchdog.py --runs runs.json --issues issues.json --out decision.json

`runs.json`   = output of `gh api repos/O/R/actions/workflows/autopilot.yml/runs?per_page=100`
`issues.json` = output of `gh issue list --label autopilot-incident --state open --json number,body,comments`

Thresholds are explicit and documented in docs/reliability/AUTOPILOT_RUNBOOK.md:
* SUCCESS_MAX_AGE_H = 8   — critical work runs every 3 h; 8 h means at least two consecutive cycles were lost
                            (plus 2 h for GitHub's observed schedule delay of up to ~77 min).
* SCHEDULE_TOLERANCE_MIN = 120 — GitHub delays scheduled runs under load; we observed 77 min on 2026-11-23.
* STUCK_AFTER_MIN = 90    — the job's own timeout is 80 min; anything still running after 90 min is hung.
* QUEUED_STUCK_MIN = 180  — a run may wait in the concurrency queue behind others; 3 h of waiting is not normal.
* MISSED_CRITICAL_ALERT = 2 — one missed slot within 24 h is reported as DEGRADED; two raise an incident.
* LIVE_FAILURES_ALERT = 3  — live polling is best-effort; only repeated failures raise an incident.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:  # imported as part of the package
    from .schedule import SCHEDULES, slots
except ImportError:  # executed as a script without installing the backend
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from fil.ops.schedule import SCHEDULES, slots  # type: ignore

SUCCESS_MAX_AGE_H = 8
SCHEDULE_TOLERANCE_MIN = 120
STUCK_AFTER_MIN = 90
QUEUED_STUCK_MIN = 180
MISSED_CRITICAL_ALERT = 2
LIVE_FAILURES_ALERT = 3
LOOKBACK_H = 24
LABEL = "autopilot-incident"
FP_MARK = "<!-- watchdog-fingerprint:"

ORDER = {"HEALTHY": 0, "DEGRADED": 1, "STALE": 2, "FAILED": 3}


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


BOT = "github-actions[bot]"


def _schedule_of(run: dict) -> str | None:
    """The schedule slot a run serves. Cron-triggered runs carry the cron string in their title; runs started by
    the dispatcher (workflow_dispatch by github-actions[bot]) carry the job name (`Autopilot · <job>`)."""
    title = run.get("display_title") or run.get("name") or ""
    for cron in SCHEDULES:
        if cron in title:
            return cron
    if _is_automatic_dispatch(run):
        for cron, (job, _k, _d) in SCHEDULES.items():
            if title.endswith(f"· {job}"):
                return cron
    return None


def _is_automatic_dispatch(run: dict) -> bool:
    return run.get("event") == "workflow_dispatch" and (run.get("triggering_actor") or {}).get("login") == BOT


def _job_kind(run: dict) -> str:
    """'critical', 'best_effort' (live polling) or 'manual' (owner-dispatched; failures are reported, not alerted)."""
    if run.get("event") == "workflow_dispatch" and not _is_automatic_dispatch(run):
        return "manual"
    cron = _schedule_of(run)
    if cron:
        return SCHEDULES[cron][1]
    title = (run.get("display_title") or "").lower()
    return "best_effort" if title.endswith("live") else "critical"


def evaluate(runs: list[dict], now: datetime, first_seen: datetime | None = None) -> dict:
    """Pure function: runs (GitHub API objects, newest first or any order) -> health report."""
    runs = sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True)
    findings: list[dict] = []

    def add(severity: str, code: str, msg: str):
        findings.append({"severity": severity, "code": code, "message": msg})

    done = [r for r in runs if r.get("status") == "completed"]
    ok = [r for r in done if r.get("conclusion") == "success"]
    last_ok = _ts(ok[0]["updated_at"]) if ok else None
    # a successful manual run also did the critical work (fresh predictions, persisted DB)
    last_ok_critical = next((_ts(r["updated_at"]) for r in ok if _job_kind(r) in ("critical", "manual")
                             and not (r.get("display_title") or "").lower().endswith("live")), None)

    # 1. stuck runs
    for r in runs:
        st = r.get("status")
        if st in ("in_progress", "queued", "waiting", "requested", "pending"):
            running = st == "in_progress"
            since = _ts(r.get("run_started_at") if running else r.get("created_at")) or _ts(r.get("created_at"))
            limit = STUCK_AFTER_MIN if running else QUEUED_STUCK_MIN
            if since and now - since > timedelta(minutes=limit):
                add("FAILED", "stuck", f"run {r['id']} has been {st} for {int((now - since).total_seconds() // 60)} min "
                                       f"(limit {limit}) — {r.get('html_url', '')}")

    # 2. failures (critical vs best effort), consecutive counts
    crit_done = [r for r in done if _job_kind(r) == "critical"]
    live_done = [r for r in done if _job_kind(r) == "best_effort"]
    manual_done = [r for r in done if _job_kind(r) == "manual"]
    if manual_done and manual_done[0].get("conclusion") != "success":
        add("DEGRADED", "manual_failure", f"latest manually started run ended {manual_done[0].get('conclusion')} "
                                          f"({manual_done[0].get('display_title')}) — {manual_done[0].get('html_url', '')}")

    def consecutive_bad(rs):
        n = 0
        for r in rs:
            if r.get("conclusion") == "success":
                break
            if r.get("conclusion") in ("failure", "timed_out", "cancelled", "startup_failure"):
                n += 1
        return n

    c_bad, l_bad = consecutive_bad(crit_done), consecutive_bad(live_done)
    if c_bad:
        last = crit_done[0]
        add("FAILED", "critical_failure",
            f"{c_bad} consecutive critical Autopilot run(s) did not succeed; latest: {last.get('conclusion')} "
            f"({last.get('display_title')}) — {last.get('html_url', '')}")
    if l_bad >= LIVE_FAILURES_ALERT:
        add("DEGRADED", "live_failures", f"{l_bad} consecutive live-polling runs did not succeed")
    elif l_bad:
        add("DEGRADED", "live_failure", f"latest live-polling run: {live_done[0].get('conclusion')}")

    # 3. staleness of the last successful critical work
    if last_ok_critical is None:
        add("STALE", "no_success", "no successful critical Autopilot run in the inspected history")
    else:
        age_h = (now - last_ok_critical).total_seconds() / 3600
        if age_h > SUCCESS_MAX_AGE_H:
            add("STALE", "success_overdue", f"last successful critical run finished {age_h:.1f} h ago "
                                            f"(limit {SUCCESS_MAX_AGE_H} h)")

    # 4. missed scheduled slots (no scheduled run started within the tolerance window)
    start = now - timedelta(hours=LOOKBACK_H)
    if first_seen and first_seen > start:
        start = first_seen  # do not report slots from before the schedule existed
    end = now - timedelta(minutes=SCHEDULE_TOLERANCE_MIN)
    sched_runs = sorted((r for r in runs if r.get("event") == "schedule" or _schedule_of(r)), key=lambda r: r["created_at"])
    used: set = set()
    missed = {"critical": [], "best_effort": []}
    expected = {"critical": 0, "best_effort": 0}
    all_slots = sorted((t, cron) for cron in SCHEDULES for t in slots(cron, start, end))
    for t, cron in all_slots:
        kind = SCHEDULES[cron][1]
        expected[kind] += 1
        hit = None
        for r in sched_runs:
            if r["id"] in used:
                continue
            tagged = _schedule_of(r)
            if tagged is not None and tagged != cron:
                continue
            c = _ts(r["created_at"])
            if t <= c <= t + timedelta(minutes=SCHEDULE_TOLERANCE_MIN):
                hit = r
                break
        if hit:
            used.add(hit["id"])
        else:
            missed[kind].append(f"{t:%Y-%m-%d %H:%M} UTC ({SCHEDULES[cron][2]})")
    if len(missed["critical"]) >= MISSED_CRITICAL_ALERT:
        add("FAILED", "missed_schedules", f"{len(missed['critical'])} critical scheduled slots in the last "
                                          f"{LOOKBACK_H} h never started: " + "; ".join(missed["critical"][:8]))
    elif missed["critical"]:
        add("DEGRADED", "missed_schedule", "critical scheduled slot never started: " + missed["critical"][0])
    if missed["best_effort"]:
        add("DEGRADED", "missed_live", f"{len(missed['best_effort'])} live-polling slots never started")

    status = max((f["severity"] for f in findings), key=lambda s: ORDER[s], default="HEALTHY")
    alert_codes = {"stuck", "critical_failure", "no_success", "success_overdue", "missed_schedules", "live_failures"}
    alert = [f for f in findings if f["code"] in alert_codes]
    recent = [r for r in done if _ts(r["created_at"]) >= now - timedelta(hours=LOOKBACK_H)]
    durations = [(_ts(r["updated_at"]) - _ts(r.get("run_started_at") or r["created_at"])).total_seconds() / 60
                 for r in recent]
    score = {
        "window_h": LOOKBACK_H,
        "scheduled_slots_expected": expected,
        "scheduled_slots_missed": {k: len(v) for k, v in missed.items()},
        "runs_completed": len(recent),
        "runs_succeeded": sum(1 for r in recent if r.get("conclusion") == "success"),
        "runs_failed": sum(1 for r in recent if r.get("conclusion") in ("failure", "timed_out", "startup_failure")),
        "runs_cancelled": sum(1 for r in recent if r.get("conclusion") == "cancelled"),
        "success_rate": round(sum(1 for r in recent if r.get("conclusion") == "success") / len(recent), 3) if recent else None,
        "consecutive_critical_failures": c_bad,
        "mean_duration_min": round(sum(durations) / len(durations), 1) if durations else None,
        "longest_duration_min": round(max(durations), 1) if durations else None,
        "last_success_utc": last_ok.isoformat() + "Z" if last_ok else None,
        "last_critical_success_utc": last_ok_critical.isoformat() + "Z" if last_ok_critical else None,
    }
    fp = hashlib.sha1(json.dumps(sorted(f["code"] for f in alert)).encode()).hexdigest()[:12] if alert else None
    return {"status": status, "alert": bool(alert), "fingerprint": fp, "findings": findings, "scorecard": score,
            "missed": missed, "evaluated_at": now.isoformat() + "Z"}


ACTIVE = ("in_progress", "queued", "waiting", "requested", "pending")
CATCH_UP_AFTER_H = 3.5     # critical work is due every 3 h
DAILY_AFTER_H = 26
CATCH_UP_COOLDOWN_H = 3    # at most one automatic catch-up per 3 h, so a failing job cannot loop


def catch_up(runs: list[dict], dispatcher_runs: list[dict], now: datetime) -> list[dict]:
    """Self-healing actions: restart the dispatcher if none is running, and start overdue critical work."""
    acts = []
    if not any(r.get("status") in ACTIVE for r in dispatcher_runs):
        acts.append({"workflow": "dispatcher.yml", "job": None, "reason": "no dispatcher running"})
    if any(r.get("status") in ACTIVE for r in runs):
        return acts
    recent_auto = [r for r in runs if _is_automatic_dispatch(r)
                   and now - _ts(r["created_at"]) < timedelta(hours=CATCH_UP_COOLDOWN_H)
                   and r.get("conclusion") not in (None, "success")]
    if recent_auto:
        return acts  # an automatic attempt already failed recently: escalate via the issue, do not loop

    def last_success(pred):
        t = [_ts(r["updated_at"]) for r in runs if r.get("conclusion") == "success" and pred(r)]
        return max(t) if t else None

    title = lambda r: r.get("display_title") or ""
    last_daily = last_success(lambda r: "10 5 * * *" in title(r) or title(r).endswith("· daily"))
    last_crit = last_success(lambda r: not title(r).endswith("live") and "7,27,47" not in title(r))
    if last_daily is None or now - last_daily > timedelta(hours=DAILY_AFTER_H):
        acts.append({"workflow": "autopilot.yml", "job": "daily", "reason": "no successful daily run in 26 h"})
    elif last_crit is None or now - last_crit > timedelta(hours=CATCH_UP_AFTER_H):
        acts.append({"workflow": "autopilot.yml", "job": "results,fixtures_odds",
                     "reason": f"no successful critical run in {CATCH_UP_AFTER_H} h"})
    return acts


def decide(report: dict, open_issues: list[dict]) -> dict:
    """Issue action with de-duplication: one open incident issue at a time; comment only when the set of
    problems changes; close it (with a recovery note) once healthy again."""
    issue = open_issues[0] if open_issues else None
    if report["alert"]:
        if issue is None:
            return {"action": "create", "title": f"Autopilot incident: {report['status']} — "
                                                  f"{', '.join(sorted({f['code'] for f in report['findings'] if f['severity'] != 'DEGRADED'}))}",
                    "body": render(report)}
        texts = [issue.get("body") or ""] + [c.get("body") or "" for c in issue.get("comments") or []]
        last_fp = next((t.split(FP_MARK)[1].split("-->")[0].strip() for t in reversed(texts) if FP_MARK in t), None)
        if last_fp == report["fingerprint"]:
            return {"action": "none", "issue": issue["number"], "reason": "same incident already reported"}
        return {"action": "comment", "issue": issue["number"], "body": render(report)}
    if issue is not None:
        return {"action": "close", "issue": issue["number"],
                "body": "✅ **Recovered.** The watchdog no longer sees an incident.\n\n" + render(report)}
    return {"action": "none", "reason": "healthy" if report["status"] == "HEALTHY" else "degraded, below alert threshold"}


def render(report: dict) -> str:
    lines = [f"**Autopilot status: {report['status']}** (evaluated {report['evaluated_at']})", ""]
    for f in report["findings"]:
        lines.append(f"- `{f['severity']}` **{f['code']}** — {f['message']}")
    if not report["findings"]:
        lines.append("- no findings")
    s = report["scorecard"]
    lines += ["", f"| Last {s['window_h']} h | Value |", "|---|---|",
              f"| Critical slots expected / missed | {s['scheduled_slots_expected']['critical']} / {s['scheduled_slots_missed']['critical']} |",
              f"| Live slots expected / missed | {s['scheduled_slots_expected']['best_effort']} / {s['scheduled_slots_missed']['best_effort']} |",
              f"| Runs completed / succeeded / failed / cancelled | {s['runs_completed']} / {s['runs_succeeded']} / {s['runs_failed']} / {s['runs_cancelled']} |",
              f"| Success rate | {s['success_rate'] if s['success_rate'] is not None else '—'} |",
              f"| Mean / longest duration (min) | {s['mean_duration_min'] or '—'} / {s['longest_duration_min'] or '—'} |",
              f"| Last critical success | {s['last_critical_success_utc'] or 'none'} |",
              "", "What to do: see `docs/reliability/AUTOPILOT_RUNBOOK.md` (section 4, 'How to identify a failed run').",
              "", f"{FP_MARK} {report['fingerprint'] or 'none'} -->"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--issues")
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-seen", help="ISO time the current schedule was introduced (ignore earlier slots)")
    ap.add_argument("--dispatcher-runs", help="runs of dispatcher.yml (enables catch-up decisions)")
    ap.add_argument("--now", help="override the current time (tests)")
    a = ap.parse_args(argv)
    runs = json.loads(Path(a.runs).read_text()).get("workflow_runs", [])
    issues = json.loads(Path(a.issues).read_text()) if a.issues and Path(a.issues).exists() else []
    now = _ts(a.now) if a.now else datetime.now(timezone.utc).replace(tzinfo=None)
    rep = evaluate(runs, now, _ts(a.first_seen) if a.first_seen else None)
    rep["decision"] = decide(rep, issues)
    if a.dispatcher_runs and Path(a.dispatcher_runs).exists():
        rep["catch_up"] = catch_up(runs, json.loads(Path(a.dispatcher_runs).read_text()).get("workflow_runs", []), now)
    else:
        rep["catch_up"] = []
    Path(a.out).write_text(json.dumps(rep, indent=1))
    print(render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
