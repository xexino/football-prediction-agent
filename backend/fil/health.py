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
OVERDUE_H = 3            # a match is over ~2 h after kickoff; +1 h for providers to publish
OVERDUE_STALE_H = 36     # football-data.co.uk usually publishes lower-league results within a day
OVERDUE_STALE_MIN = 5
ORPHAN_H = 72            # after 3 days a match whose whole round has results is treated as unresolved, not stale    # several matches that late means results collection is broken, not one postponed game
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
        n_up = s.scalar(select(func.count(Fixture.id)).where(Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                                                             Fixture.kickoff_utc < now + timedelta(days=7)))
        if newest_odds is None and n_up:
            # the feed runs but nothing upcoming is priced: that is a coverage gap (no bets possible), not "unknown"
            # (council cycle 2026-11-27 06:50: UNKNOWN while 0 of 91 weekend fixtures had odds)
            last_feed = s.scalar(select(func.max(OddsObservation.retrieved_at)).where(OddsObservation.kind == "pre_match"))
            comps["odds"] = {"state": "DEGRADED", "age_h": None, "last": iso(last_feed), "with_odds": 0, "upcoming_7d": n_up,
                             "detail": f"0 of {n_up} upcoming fixtures have pre-match odds (last odds feed "
                                       f"{iso(last_feed) or 'never'}); no virtual bets are possible until odds arrive"}
        upcoming = n_up
        newest_result = s.scalar(select(func.max(Fixture.kickoff_utc)).where(Fixture.status == "finished",
                                                                         Fixture.first_seen_source == "football_data_uk"))
        comps["fixtures"] = {"state": "HEALTHY" if upcoming else "DEGRADED", "upcoming_7d": upcoming,
                             "newest_result_kickoff": iso(newest_result),
                             "detail": "no upcoming fixtures known" if not upcoming else f"{upcoming} upcoming in 7 days"}
        # overdue results: matches whose kickoff is well past but no verified score has arrived (audit 2026-11-25:
        # 30 such fixtures while everything reported HEALTHY). Window: the last 14 days (older ones are listed in
        # integrity reports, not here, so one abandoned fixture cannot keep the system red forever).
        overdue_all = s.execute(select(Fixture.id, Fixture.kickoff_utc, Fixture.competition_id).where(
            Fixture.status == "scheduled", Fixture.kickoff_utc < now - timedelta(hours=OVERDUE_H),
            Fixture.kickoff_utc > now - timedelta(days=400))).all()
        # "unresolved (round complete)": > 72 h old while every other match of its competition within +-3 days has a
        # result -> almost certainly postponed/abandoned and dropped by the source. Shown, but kept out of the stale
        # alarm. The stored status is NOT changed (a guessed 'postponed' would void bets; council 2026-11-25 12:51).
        unresolved = []
        for r in overdue_all:
            if r.kickoff_utc > now - timedelta(hours=ORPHAN_H):
                continue
            sib = s.execute(select(Fixture.status).where(
                Fixture.competition_id == r.competition_id, Fixture.id != r.id,
                Fixture.kickoff_utc.between(r.kickoff_utc - timedelta(days=3), r.kickoff_utc + timedelta(days=3)))).scalars().all()
            if len(sib) >= 3 and all(x == "finished" for x in sib):
                unresolved.append(r.id)
        overdue = [r for r in overdue_all if r.id not in unresolved and r.kickoff_utc > now - timedelta(days=14)]
        # only matches we monitor raise the alarm: an eligible competition, or anything with a prediction or a bet.
        # Unmonitored, source-limited leagues (e.g. TheSportsDB-only EGY1/RSA1) stay visible as a backlog
        # (council cycle 2026-11-27 06:50). A failed predict step cannot hide here: eligible competitions always count.
        from .db import Competition, EBPrediction, Prediction, VirtualBet

        eligible_ids = set(s.scalars(select(Competition.id).where(Competition.eligible.is_(True))))
        ids = [r.id for r in overdue] or [-1]
        watched = (set(s.scalars(select(Prediction.fixture_id).where(Prediction.fixture_id.in_(ids))))
                   | set(s.scalars(select(EBPrediction.fixture_id).where(EBPrediction.fixture_id.in_(ids))))
                   | set(s.scalars(select(VirtualBet.fixture_id).where(VirtualBet.fixture_id.in_(ids)))))
        unmonitored = [r for r in overdue if r.competition_id not in eligible_ids and r.id not in watched]
        overdue = [r for r in overdue if r not in unmonitored]
        very_late = [r for r in overdue if r.kickoff_utc < now - timedelta(hours=OVERDUE_STALE_H)]
        backlog: dict[str, int] = {}
        if unmonitored:
            codes = dict(s.execute(select(Competition.id, Competition.code)).all())
            for r in unmonitored:
                backlog[codes.get(r.competition_id, "?")] = backlog.get(codes.get(r.competition_id, "?"), 0) + 1
        comps["results"] = {"state": "HEALTHY" if not overdue else ("STALE" if len(very_late) >= OVERDUE_STALE_MIN else "DEGRADED"),
                            "overdue": len(overdue), "overdue_24h": len(very_late),
                            "unresolved_round_complete": unresolved, "unmonitored_backlog": backlog,
                            "detail": ((f"{len(overdue)} matches kicked off more than {OVERDUE_H} h ago and still have no verified result "
                                        f"({len(very_late)} older than {OVERDUE_STALE_H} h); lower leagues depend on "
                                        "football-data.co.uk, which publishes with a delay") if overdue else
                                       "every match that kicked off more than 3 h ago has a result")
                                      + (f"; {len(unresolved)} older match(es) never got a result although the rest of "
                                         "their round did (probably postponed; not counted as stale)" if unresolved else "")
                                      + (f"; unmonitored backlog (no prediction, no bet): "
                                         + ", ".join(f"{k} {v}" for k, v in sorted(backlog.items())) if backlog else "")}
        # live data: informational (never critical). Age of the newest live snapshot, labelled honestly.
        from .db import EBLiveSnapshot

        newest_live = s.scalar(select(func.max(EBLiveSnapshot.created_at)))
        # a stale live feed only matters while a match it covers could be in play (live polling: football-data.org
        # competitions, 11-23 UTC). Otherwise it is idle, not degraded (it was DEGRADED every night by design).
        live_comp_ids = [c.id for c in s.scalars(select(Competition)) if "fdorg" in (c.sources or {})] or [-1]
        polling = 11 <= now.hour <= 23  # live slots "7,27,47 11-23 * * *" (ops/schedule.py): outside them, idle by design
        in_play = polling and s.scalar(select(func.count(Fixture.id)).where(
            Fixture.competition_id.in_(live_comp_ids), Fixture.kickoff_utc <= now,
            Fixture.kickoff_utc > now - timedelta(hours=2, minutes=30),
            Fixture.status.notin_(("postponed", "cancelled", "abandoned")))) > 0
        live_fresh = newest_live is not None and now - newest_live < timedelta(minutes=45)
        comps["live"] = {"state": "UNKNOWN" if newest_live is None else
                         ("HEALTHY" if live_fresh or not in_play else "DEGRADED"), "idle": not live_fresh and not in_play,
                         "last": iso(newest_live),
                         "detail": "no live snapshot yet" if newest_live is None else
                         ("idle: no covered match in play" if not live_fresh and not in_play else
                          "newest live snapshot; free-plan feeds are DELAYED, never real-time")}
        providers = {}
        for k, d in ds.items():
            if not d.configured:
                state = "UNKNOWN"
            elif d.status == "ok":
                state = "HEALTHY"
            elif d.status == "degraded":
                state = "DEGRADED"
            elif d.status == "error":
                state = "FAILED" if (d.last_success_at is None or now - d.last_success_at > timedelta(hours=30)) else "DEGRADED"
            else:
                state = "UNKNOWN"
            providers[k] = {"state": state, "configured": d.configured, "last_success": iso(d.last_success_at),
                            "last_error": (d.last_error or "")[:200] or None, "circuit": (d.quota_info or {}).get("circuit"),
                            "error_kind": (d.quota_info or {}).get("last_error_kind") if d.status in ("error", "degraded") else None}
    if include_db_check:
        from .integrity import check_database

        try:
            chk = check_database()
            comps["database"] = {"state": "HEALTHY" if chk["ok"] else "FAILED", "problems": chk["problems"],
                                 "counts": chk["counts"]}
        except Exception as exc:
            comps["database"] = {"state": "FAILED", "problems": [str(exc)]}
    critical = ["collection", "predictions", "settlement", "database", "last_run", "scheduler", "results"]
    overall = max((comps[c]["state"] for c in critical if c in comps), key=lambda x: ORDER[x])
    return {"overall": overall, "components": comps, "providers": providers, "computed_at": iso(now),
            "states": {"HEALTHY": "working and recent", "DEGRADED": "partly working, or slightly late",
                       "FAILED": "last attempt failed / integrity problem", "STALE": "no successful update for too long",
                       "UNKNOWN": "never ran or not configured"}}
