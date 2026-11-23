"""Single source of truth for the Autopilot schedule (stdlib only, so the watchdog can import it without
installing the backend dependencies).

Every cron line in `.github/workflows/autopilot.yml` MUST appear in SCHEDULES (a test enforces this), and
routing is explicit: an unknown schedule string is an error, never a silent default job.

GitHub Actions cron is evaluated in UTC. There is no daylight-saving adjustment: the daily run is 06:10 in
Rome in winter (CET, UTC+1) and 07:10 in summer (CEST, UTC+2).
"""
from __future__ import annotations

from datetime import datetime, timedelta

# cron -> (job list, criticality, human description)
# criticality "critical": a missed or failed run can create a permanent gap (predictions must exist before
# kickoff, settlement, backups). "best_effort": live polling, where a missed slot has no lasting effect.
SCHEDULES: dict[str, tuple[str, str, str]] = {
    "10 5 * * *": ("daily", "critical", "daily full cycle"),
    "40 */3 * * *": ("results,fixtures_odds", "critical", "results + fixtures/odds + predictions every 3 h"),
    "25 6 * * 1": ("weekly", "critical", "weekly report, backtests and Engine B validation (Monday)"),
    "7,27,47 11-23 * * *": ("live", "best_effort", "live polling during match hours"),
}

JOBS = ("daily", "fixtures_odds", "results", "prematch_review", "weekly", "live", "engine_b", "backup", "bootstrap")


class RoutingError(ValueError):
    pass


def route(event: str, schedule: str = "", requested: str = "", db_source: str = "release") -> str:
    """Decide which backend job(s) a workflow run executes. Returns a comma-separated job list."""
    if db_source == "none":
        return "bootstrap"
    if event == "workflow_dispatch":
        jobs = [j.strip() for j in (requested or "daily").split(",") if j.strip()]
        bad = [j for j in jobs if j not in JOBS]
        if bad or not jobs:
            raise RoutingError(f"unknown job(s) {bad or requested!r}; allowed: {', '.join(JOBS)}")
        return ",".join(jobs)
    if event == "schedule":
        if schedule not in SCHEDULES:
            raise RoutingError(f"schedule {schedule!r} is not in fil/ops/schedule.py SCHEDULES")
        return SCHEDULES[schedule][0]
    raise RoutingError(f"unsupported event {event!r}")


# --------------------------------------------------------------------------- minimal cron evaluator
def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
        if a < lo or b > hi or a > b or step < 1:
            raise ValueError(f"invalid cron field {spec!r}")
        out.update(range(a, b + 1, step))
    return out


def parse(cron: str) -> tuple[set[int], ...]:
    f = cron.split()
    if len(f) != 5:
        raise ValueError(f"cron needs 5 fields: {cron!r}")
    minute, hour, dom, month, dow = (_field(f[0], 0, 59), _field(f[1], 0, 23), _field(f[2], 1, 31),
                                     _field(f[3], 1, 12), _field(f[4].replace("7", "0"), 0, 6))
    return minute, hour, dom, month, dow


def matches(cron: str, t: datetime) -> bool:
    minute, hour, dom, month, dow = parse(cron)
    return (t.minute in minute and t.hour in hour and t.day in dom and t.month in month
            and (t.isoweekday() % 7) in dow)


def slots(cron: str, start: datetime, end: datetime) -> list[datetime]:
    """All scheduled times in [start, end) (naive UTC, minute resolution)."""
    t = start.replace(second=0, microsecond=0)
    if t < start:
        t += timedelta(minutes=1)
    out = []
    minute, hour, *_ = parse(cron)
    while t < end:
        if t.hour not in hour:  # skip whole hours quickly
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if matches(cron, t):
            out.append(t)
        t += timedelta(minutes=1)
    return out


def main() -> int:
    """`python -m fil.ops.schedule` — reads EVENT, SCHEDULE, REQUESTED, DB_SOURCE from the environment (never
    from string-interpolated workflow expressions) and prints the job list, or exits 2 on an unknown route."""
    import os
    import sys

    try:
        print(route(os.environ.get("EVENT", ""), os.environ.get("SCHEDULE", ""), os.environ.get("REQUESTED", ""),
                    os.environ.get("DB_SOURCE", "release")))
        return 0
    except RoutingError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
