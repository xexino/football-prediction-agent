"""Operational health model.

States: HEALTHY, DEGRADED, FAILED, STALE, UNKNOWN. A component is judged on what it actually
produced recently (freshness of its last *successful* work), not on whether a process exited cleanly.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from .db import DataSource, Fixture, JobRun, OddsObservation, session_scope
from .timeutil import iso, utcnow

ORDER = {"HEALTHY": 0, "UNKNOWN": 1, "DEGRADED": 2, "STALE": 3, "FAILED": 4}
# expected cadence: autopilot every 3h, daily cycle every 24h
THRESHOLDS = {  # component: (healthy_if_younger_than_h, warning_if_younger_than_h)
    "collection": (8, 30), "predictions": (8, 30), "settlement": (12, 36), "backup": (30, 54),
    "odds": (72, 120), "scheduler": (7, 26),
}


def _age_state(ts: datetime | None, comp: str, now: datetime) -> tuple[str, float | None]:
    if ts is None:
        return "UNKNOWN", None
    age = (now - ts).total_seconds() / 3600
    h, w = THRESHOLDS[comp]
    return ("HEALTHY" if age < h else "DEGRADED" if age < w else "STALE"), round(age, 1)


def _last_step(s, step: str):
    for r in s.scalars(select(JobRun).where(JobRun.finished_at.is_not(None)).order_by(JobRun.id.desc()).limit(300)):
        st = ((r.summary or {}).get("steps") or {}).get(step)
        if st and st.get("status") == "success":
            return r.finished_at
        if r.status == "success" and step in (r.summary or {}):  # runs recorded before step tracking
            return r.finished_at
        # bootstrap/daily legacy nesting
        legacy = (r.summary or {}).get("daily") if r.status == "success" else None
        if isinstance(legacy, dict) and step in legacy:
            return r.finished_at
    return None


def compute(now: datetime | None = None, include_db_check: bool = True) -> dict:
    now = now or utcnow()
    comps = {}
    with session_scope() as s:
        # collection = last successful retrieval from the primary provider
        ds = {d.key: d for d in s.scalars(select(DataSource))}
        prim = ds.get("football_data_uk")
        st, age = _age_state(prim.last_success_at if prim else None, "collection", now)
        if prim and prim.status == "error" and st != "HEALTHY":
            st = "FAILED"
        comps["collection"] = {"state": st, "age_h": age, "last": iso(prim.last_success_at) if prim else None,
                               "detail": "football-data.co.uk results/fixtures/odds"}
        for comp, step in (("predictions", "predict"), ("settlement", "settle"), ("backup", "backup")):
            ts = _last_step(s, step)
            st, age = _age_state(ts, comp, now)
            comps[comp] = {"state": st, "age_h": age, "last": iso(ts)}
        last_any = s.scalars(select(JobRun).where(JobRun.status.not_in(["skipped", "running"]))
                             .order_by(JobRun.id.desc())).first()
        st, age = _age_state(last_any.finished_at if last_any else None, "scheduler", now)
        comps["scheduler"] = {"state": st, "age_h": age, "last": iso(last_any.finished_at) if last_any else None,
                              "detail": "time since the last automated run finished"}
        if last_any is None:
            comps["last_run"] = {"state": "UNKNOWN"}
        else:
            comps["last_run"] = {"state": {"success": "HEALTHY", "partial": "DEGRADED", "error": "FAILED",
                                           "interrupted": "FAILED"}.get(last_any.status, "UNKNOWN"),
                                 "job": last_any.job, "status": last_any.status, "last": iso(last_any.finished_at),
                                 "failed_steps": [k for k, v in ((last_any.summary or {}).get("steps") or {}).items()
                                                  if v.get("status") == "error"]}
        # odds freshness for fixtures in the next 7 days
        newest_odds = s.scalar(select(func.max(OddsObservation.retrieved_at)).join(Fixture, Fixture.id == OddsObservation.fixture_id)
                               .where(Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                                      Fixture.kickoff_utc < now + timedelta(days=7), OddsObservation.kind == "pre_match"))
        st, age = _age_state(newest_odds, "odds", now)
        comps["odds"] = {"state": st, "age_h": age, "last": iso(newest_odds),
                         "detail": "newest pre-match odds for upcoming fixtures (source publishes ~2x/week)"}
        upcoming = s.scalar(select(func.count(Fixture.id)).where(Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                                                              Fixture.kickoff_utc < now + timedelta(days=7)))
        newest_result = s.scalar(select(func.max(Fixture.kickoff_utc)).where(Fixture.status == "finished",
                                                                         Fixture.first_seen_source == "football_data_uk"))
        comps["fixtures"] = {"state": "HEALTHY" if upcoming else "DEGRADED", "upcoming_7d": upcoming,
                             "newest_result_kickoff": iso(newest_result),
                             "detail": "no upcoming fixtures known" if not upcoming else f"{upcoming} upcoming in 7 days"}
        # live data: informational (never critical). Age of the newest live snapshot, labelled honestly.
        from .db import EBLiveSnapshot

        newest_live = s.scalar(select(func.max(EBLiveSnapshot.created_at)))
        comps["live"] = {"state": "UNKNOWN" if newest_live is None else
                         ("HEALTHY" if now - newest_live < timedelta(minutes=45) else "DEGRADED"),
                         "last": iso(newest_live),
                         "detail": "no live snapshot yet" if newest_live is None else
                         "newest live snapshot; free-plan feeds are DELAYED, never real-time"}
        providers = {}
        for k, d in ds.items():
            if not d.configured:
                state = "UNKNOWN"
            elif d.status == "ok":
                state = "HEALTHY"
            elif d.status == "error":
                state = "FAILED" if (d.last_success_at is None or now - d.last_success_at > timedelta(hours=30)) else "DEGRADED"
            else:
                state = "UNKNOWN"
            providers[k] = {"state": state, "configured": d.configured, "last_success": iso(d.last_success_at),
                            "last_error": (d.last_error or "")[:200] or None, "circuit": (d.quota_info or {}).get("circuit"),
                            "error_kind": (d.quota_info or {}).get("last_error_kind") if d.status == "error" else None}
    if include_db_check:
        from .integrity import check_database

        try:
            chk = check_database()
            comps["database"] = {"state": "HEALTHY" if chk["ok"] else "FAILED", "problems": chk["problems"],
                                 "counts": chk["counts"]}
        except Exception as exc:
            comps["database"] = {"state": "FAILED", "problems": [str(exc)]}
    critical = ["collection", "predictions", "settlement", "database", "last_run", "scheduler"]
    overall = max((comps[c]["state"] for c in critical if c in comps), key=lambda x: ORDER[x])
    return {"overall": overall, "components": comps, "providers": providers, "computed_at": iso(now),
            "states": {"HEALTHY": "working and recent", "DEGRADED": "partly working, or slightly late",
                       "FAILED": "last attempt failed / integrity problem", "STALE": "no successful update for too long",
                       "UNKNOWN": "never ran or not configured"}}
