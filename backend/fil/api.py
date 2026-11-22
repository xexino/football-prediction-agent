"""FastAPI application: JSON API + the built React dashboard (served from fil/static)."""
from __future__ import annotations

import hmac
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from . import __version__, scheduler
from .catalog import BY_CODE
from .config import settings
from .db import (BacktestRun, Competition, DataSource, Fixture, JobRun, MatchStats, ModelVersion, OddsObservation,
                 Prediction, Report, Settlement, SystemLog, Team, TeamNews, ValueAssessment, VirtualBet, init_db,
                 session_scope)
from .jobs import JOBS, run_job
from .models.markets import SETTLEMENT_RULES, devig
from .providers.footballdata_uk import BOOKMAKER_LABELS
from .stats import summary
from .timeutil import iso, rome, utcnow

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .collect import register_all

    register_all()
    if settings.scheduler_enabled:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Football Intelligence Lab", version=__version__, lifespan=lifespan,
              description="Football research & VIRTUAL betting simulation. No real money is ever involved.")
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ------------------------------------------------------------------ helpers
def _teams(s) -> dict:
    return {t.id: t.name for t in s.scalars(select(Team))}


def _comps(s) -> dict:
    return {c.id: c for c in s.scalars(select(Competition))}


def _fixture_dict(f: Fixture, teams, comps) -> dict:
    c = comps[f.competition_id]
    return {"id": f.id, "competition": c.code, "competition_name": c.name, "region": c.region,
            "home": teams.get(f.home_team_id), "away": teams.get(f.away_team_id),
            "home_team_id": f.home_team_id, "away_team_id": f.away_team_id,
            "kickoff_utc": iso(f.kickoff_utc), "kickoff_rome": rome(f.kickoff_utc), "status": f.status,
            "score": None if f.home_goals is None else f"{f.home_goals}-{f.away_goals}",
            "result_source": f.result_source, "result_conflict": f.result_conflict}


def _odds_summary(s, fixture_id: int, now) -> dict:
    rows = s.scalars(select(OddsObservation).where(OddsObservation.fixture_id == fixture_id,
                                                    OddsObservation.kind == "pre_match", OddsObservation.retrieved_at <= now)
                     .order_by(OddsObservation.retrieved_at)).all()
    latest = {}
    for o in rows:
        latest[o.bookmaker] = o
    out = {}
    probs = {b: devig([o.home, o.draw, o.away]) for b, o in latest.items() if o.home and o.draw and o.away and b != "Max"}
    med = None
    if len(probs) >= 2:
        import statistics

        med = [statistics.median(v[k] for v in probs.values()) for k in range(3)]
    for b, o in latest.items():
        flags = []
        if o.home and o.draw and o.away:
            ovr = sum(1 / x for x in (o.home, o.draw, o.away)) - 1
            if ovr < -0.02 or ovr > 0.20:
                flags.append(f"implausible margin {ovr:.0%}")
            if med and b in probs and max(abs(a - c) for a, c in zip(probs[b], med)) > 0.10:
                flags.append("disagrees with other bookmakers by >10pp")
        out[b] = {"label": BOOKMAKER_LABELS.get(b, b), "home": o.home, "draw": o.draw, "away": o.away,
                  "over25": o.over25, "under25": o.under25, "ah_line": o.ah_line, "ah_home": o.ah_home,
                  "ah_away": o.ah_away, "retrieved_at": iso(o.retrieved_at), "source": o.source,
                  "source_url": o.source_url, "snapshots": sum(1 for r in rows if r.bookmaker == b),
                  "suspect": bool(flags), "flags": flags,
                  "overround_1x2": round(sum(1 / x for x in (o.home, o.draw, o.away)) - 1, 4) if o.home and o.draw and o.away else None,
                  "devig_1x2": [round(x, 4) for x in devig([o.home, o.draw, o.away])] if o.home and o.draw and o.away else None}
    return out


def _pred_dict(p: Prediction, with_inputs=False) -> dict:
    d = {"id": p.id, "fixture_id": p.fixture_id, "created_at": iso(p.created_at), "created_rome": rome(p.created_at),
         "revision": p.revision, "revision_of": p.revision_of, "revision_reason": p.revision_reason,
         "probs": p.probs, "components": p.component_probs, "exp_home_goals": p.exp_home_goals,
         "exp_away_goals": p.exp_away_goals, "exp_total_goals": round(p.exp_home_goals + p.exp_away_goals, 3),
         "confidence": p.confidence, "data_quality": p.data_quality, "quality_breakdown": p.quality_breakdown,
         "decision": p.decision, "explanation": p.explanation, "sources": p.sources,
         "evaluated": p.evaluated, "eval_brier": p.eval_brier, "eval_logloss": p.eval_logloss, "eval_correct": p.eval_correct}
    if with_inputs:
        d["inputs"] = p.inputs
    return d


def _va_dict(v: ValueAssessment) -> dict:
    return {"id": v.id, "market": v.market, "selection": v.selection, "line": v.line, "price": v.price,
            "bookmaker": v.bookmaker, "implied_prob": v.implied_prob, "market_prob": v.market_prob,
            "model_prob": v.model_prob, "conservative_prob": v.conservative_prob, "overround": v.overround,
            "ev": v.ev, "ev_conservative": v.ev_conservative, "qualifies": v.qualifies, "reject_reasons": v.reject_reasons}


def _bet_dict(b: VirtualBet, f: Fixture, teams, comps, st: Settlement | None = None) -> dict:
    return {"id": b.id, "fixture": _fixture_dict(f, teams, comps), "prediction_id": b.prediction_id,
            "market": b.market, "selection": b.selection, "line": b.line, "price": b.price, "bookmaker": b.bookmaker,
            "bookmaker_label": BOOKMAKER_LABELS.get(b.bookmaker, b.bookmaker), "stake": b.stake,
            "potential_return": b.potential_return, "model_prob": b.model_prob, "ev": b.ev,
            "created_at": iso(b.created_at), "created_rome": rome(b.created_at), "status": b.status,
            "settled_at": iso(b.settled_at), "payout": b.payout, "profit": b.profit, "closing_price": b.closing_price,
            "clv": b.clv, "model_version_id": b.model_version_id,
            "settlement": None if st is None else {"outcome": st.outcome, "score": f"{st.home_goals}-{st.away_goals}",
                                                   "source": st.result_source, "rule": st.rule, "at": iso(st.settled_at)}}


# ------------------------------------------------------------------ endpoints
@app.get("/api/health")
def health():
    try:
        with session_scope() as s:
            s.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": __version__, "database": db_ok,
            "scheduler_running": scheduler.running(), "time_utc": iso(utcnow()), "simulation_only": True}


@app.get("/api/standings")
def standings():
    from .db import StandingSnapshot

    with session_scope() as s:
        comps = _comps(s)
        latest = s.execute(select(StandingSnapshot.competition_id, func.max(StandingSnapshot.snapshot_date))
                           .group_by(StandingSnapshot.competition_id)).all()
        out = {}
        for cid, day in latest:
            rows = s.scalars(select(StandingSnapshot).where(StandingSnapshot.competition_id == cid,
                                                            StandingSnapshot.snapshot_date == day)
                             .order_by(StandingSnapshot.team_name.contains("(").asc(), StandingSnapshot.position)).all()
            out[comps[cid].code] = {"competition": comps[cid].name, "snapshot_date": day, "source": "football-data.org",
                                    "rows": [{"position": r.position, "team": r.team_name, "team_id": r.team_id,
                                              "played": r.played, "won": r.won, "draw": r.draw, "lost": r.lost,
                                              "gf": r.goals_for, "ga": r.goals_against, "points": r.points,
                                              "form": r.form} for r in rows]}
        return out


@app.get("/api/health_detail")
def health_detail():
    from .health import compute

    return compute()


@app.get("/api/overview")
def overview():
    now = utcnow()
    sm = summary()
    with session_scope() as s:
        teams, comps = _teams(s), _comps(s)
        upcoming = s.scalars(select(Fixture).where(Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                                                   Fixture.kickoff_utc < now + timedelta(days=7)).order_by(Fixture.kickoff_utc)).all()
        latest_pred = {}
        if upcoming:
            for p in s.scalars(select(Prediction).where(Prediction.fixture_id.in_([f.id for f in upcoming])).order_by(Prediction.revision)):
                latest_pred[p.fixture_id] = p
        opps = s.execute(select(VirtualBet, Fixture).join(Fixture, Fixture.id == VirtualBet.fixture_id).where(
            VirtualBet.status == "pending").order_by(VirtualBet.ev.desc()).limit(8)).all()
        ds = s.scalars(select(DataSource)).all()
        last_data = max((d.last_success_at for d in ds if d.last_success_at), default=None)
        mv = s.scalars(select(ModelVersion).where(ModelVersion.active.is_(True)).order_by(ModelVersion.id.desc())).first()
        n_preds = s.scalar(select(func.count(Prediction.id)))
        last_daily = s.scalars(select(JobRun).where(JobRun.job.in_(["daily", "bootstrap"])).order_by(JobRun.id.desc())).first()
        return {
            "bankroll": {k: sm[k] for k in ("starting_bankroll", "current_bankroll", "equity", "pending_exposure",
                                            "profit", "roi", "bets", "settled", "pending", "won", "lost", "void",
                                            "win_rate", "max_drawdown", "staked", "returns", "avg_clv")},
            "pnl_curve": sm["pnl_curve"],
            "upcoming": [{**_fixture_dict(f, teams, comps),
                          "decision": latest_pred[f.id].decision if f.id in latest_pred else None,
                          "data_quality": latest_pred[f.id].data_quality if f.id in latest_pred else None,
                          "probs_1x2": latest_pred[f.id].probs["1X2"] if f.id in latest_pred else None}
                         for f in upcoming[:12]],
            "upcoming_count": len(upcoming), "predicted_count": len(latest_pred),
            "opportunities": [_bet_dict(b, f, teams, comps) for b, f in opps],
            "model": None if mv is None else {"name": mv.name, "version": mv.version, "metrics": mv.metrics,
                                              "description": mv.description},
            "predictions_total": n_preds, "last_data_update": iso(last_data),
            "last_daily_run": None if last_daily is None else {"status": last_daily.status, "at": iso(last_daily.finished_at or last_daily.started_at)},
            "scheduler_running": scheduler.running(),
        }


@app.get("/api/upcoming")
def upcoming(days: int = Query(7, ge=1, le=21), competition: str | None = None, region: str | None = None):
    now = utcnow()
    with session_scope() as s:
        teams, comps = _teams(s), _comps(s)
        q = select(Fixture).where(Fixture.status.in_(["scheduled", "postponed"]), Fixture.kickoff_utc > now - timedelta(hours=3),
                                  Fixture.kickoff_utc < now + timedelta(days=days))
        fixtures = s.scalars(q.order_by(Fixture.kickoff_utc)).all()
        ids = [f.id for f in fixtures]
        preds = {}
        for p in s.scalars(select(Prediction).where(Prediction.fixture_id.in_(ids)).order_by(Prediction.revision)):
            preds[p.fixture_id] = p
        from .db import StandingSnapshot

        pos = {}
        for r in s.scalars(select(StandingSnapshot).order_by(StandingSnapshot.snapshot_date)):
            if r.team_id:
                pos[(r.competition_id, r.team_id)] = {"position": r.position, "points": r.points, "played": r.played,
                                                      "as_of": r.snapshot_date, "source": "football-data.org"}
        news = {}
        for n in s.scalars(select(TeamNews).where(TeamNews.fixture_id.in_(ids))):
            news.setdefault(n.fixture_id, []).append({"team": teams.get(n.team_id), "type": n.news_type, "player": n.player_name,
                                                       "certainty": n.certainty, "detail": n.detail, "source": n.source})
        out = []
        for f in fixtures:
            c = comps[f.competition_id]
            if competition and c.code != competition:
                continue
            if region and c.region != region:
                continue
            p = preds.get(f.id)
            item = {**_fixture_dict(f, teams, comps), "odds": _odds_summary(s, f.id, now),
                    "team_news": news.get(f.id, []), "team_news_status": "confirmed items" if f.id in news else
                    "no team-news source connected (unverified — treat as unknown)"}
            item["odds_suspect"] = any(o.get("suspect") for o in item["odds"].values())
            item["table"] = {side: pos.get((f.competition_id, tid)) for side, tid in (("home", f.home_team_id), ("away", f.away_team_id))}
            if p is not None:
                item["prediction"] = _pred_dict(p, with_inputs=True)
                item["value"] = [_va_dict(v) for v in s.scalars(select(ValueAssessment).where(ValueAssessment.prediction_id == p.id))]
                clean = [v for v in item["value"] if v["ev_conservative"] is not None
                         and not any("data error" in r or "too large" in r for r in v["reject_reasons"])]
                item["best_value"] = max(clean, key=lambda v: v["ev_conservative"], default=None)
                item["data_error_markets"] = sorted({v["market"] for v in item["value"]
                                                     if any("data error" in r for r in v["reject_reasons"])})
            else:
                cov = c.coverage or {}
                reasons = cov.get("reasons") or []
                if f.kickoff_utc <= now + timedelta(minutes=10):
                    reasons = ["kickoff too close / in progress — no new predictions"]
                elif not reasons:
                    reasons = ["teams lack sufficient history in this competition, or prediction pending next run"]
                item["ineligible_reasons"] = reasons
                item["coverage_label"] = ("DATA COVERAGE ONLY — PREDICTIONS NOT ENABLED" if not c.eligible
                                          else "INSUFFICIENT DATA" if f.kickoff_utc > now else "STARTED")
            out.append(item)
        return {"fixtures": out, "generated_at": iso(now), "data_mode": "pre-match (periodically refreshed); no live feed connected"}


@app.get("/api/predictions")
def predictions(decision: str | None = None, competition: str | None = None, team: str | None = None,
                date_from: str | None = None, date_to: str | None = None, evaluated: bool | None = None,
                limit: int = Query(200, le=2000), offset: int = 0):
    with session_scope() as s:
        teams, comps = _teams(s), _comps(s)
        q = select(Prediction, Fixture).join(Fixture, Fixture.id == Prediction.fixture_id)
        if decision:
            q = q.where(Prediction.decision == decision)
        if evaluated is not None:
            q = q.where(Prediction.evaluated.is_(evaluated))
        if date_from:
            q = q.where(Fixture.kickoff_utc >= datetime.fromisoformat(date_from))
        if date_to:
            q = q.where(Fixture.kickoff_utc < datetime.fromisoformat(date_to) + timedelta(days=1))
        rows = s.execute(q.order_by(Prediction.created_at.desc(), Prediction.id.desc())).all()
        out = []
        for p, f in rows:
            fd = _fixture_dict(f, teams, comps)
            if competition and fd["competition"] != competition:
                continue
            if team and team.lower() not in (fd["home"] or "").lower() + "|" + (fd["away"] or "").lower():
                continue
            out.append({**_pred_dict(p), "fixture": fd})
        return {"total": len(out), "items": out[offset:offset + limit]}


@app.get("/api/predictions/{pid}")
def prediction_detail(pid: int):
    with session_scope() as s:
        p = s.get(Prediction, pid)
        if p is None:
            raise HTTPException(404)
        teams, comps = _teams(s), _comps(s)
        f = s.get(Fixture, p.fixture_id)
        revs = s.scalars(select(Prediction).where(Prediction.fixture_id == p.fixture_id).order_by(Prediction.revision)).all()
        return {**_pred_dict(p, with_inputs=True), "fixture": _fixture_dict(f, teams, comps),
                "value": [_va_dict(v) for v in s.scalars(select(ValueAssessment).where(ValueAssessment.prediction_id == p.id))],
                "revisions": [{"id": r.id, "revision": r.revision, "created_at": iso(r.created_at), "reason": r.revision_reason,
                               "probs_1x2": r.probs["1X2"], "decision": r.decision} for r in revs]}


@app.get("/api/bets")
def bets(status: str | None = None, competition: str | None = None, market: str | None = None, team: str | None = None,
         model: int | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = Query(500, le=5000)):
    with session_scope() as s:
        teams, comps = _teams(s), _comps(s)
        sts = {x.bet_id: x for x in s.scalars(select(Settlement))}
        q = select(VirtualBet, Fixture).join(Fixture, Fixture.id == VirtualBet.fixture_id)
        if status:
            q = q.where(VirtualBet.status.in_(status.split(",")))
        if market:
            q = q.where(VirtualBet.market == market)
        if model:
            q = q.where(VirtualBet.model_version_id == model)
        if date_from:
            q = q.where(VirtualBet.kickoff_utc >= datetime.fromisoformat(date_from))
        if date_to:
            q = q.where(VirtualBet.kickoff_utc < datetime.fromisoformat(date_to) + timedelta(days=1))
        from .db import BankrollTransaction

        stake_tx = {t.bet_id: t for t in s.scalars(select(BankrollTransaction).where(BankrollTransaction.tx_type == "stake"))}
        settle_tx = {t.bet_id: t for t in s.scalars(select(BankrollTransaction).where(BankrollTransaction.tx_type.in_(["payout", "refund"])))}
        preds = {p.id: p for p in s.scalars(select(Prediction).where(Prediction.id.in_(select(VirtualBet.prediction_id))))}
        import bisect

        all_tx = s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.created_at, BankrollTransaction.id)).all()
        tx_times = [t.created_at for t in all_tx]
        out = []
        for b, f in s.execute(q.order_by(VirtualBet.created_at.desc())).all():
            d = _bet_dict(b, f, teams, comps, sts.get(b.id))
            st = stake_tx.get(b.id)
            d["bankroll_before"] = round(st.balance_after + b.stake, 2) if st else None
            d["bankroll_after_stake"] = st.balance_after if st else None
            if b.id in settle_tx:
                d["bankroll_after_settlement"] = settle_tx[b.id].balance_after
            elif b.settled_at is not None:  # lost bet: no credit, bankroll as it stood at settlement
                i = bisect.bisect_right(tx_times, b.settled_at) - 1
                d["bankroll_after_settlement"] = all_tx[i].balance_after if i >= 0 else None
            else:
                d["bankroll_after_settlement"] = None
            pr = preds.get(b.prediction_id)
            d["data_quality"] = pr.data_quality if pr else None
            d["confidence"] = pr.confidence if pr else None
            d["reason"] = next((x for x in (pr.explanation.split("VALUE: ")[1:] if pr else [])), None)
            if competition and d["fixture"]["competition"] != competition:
                continue
            if team and team.lower() not in (d["fixture"]["home"] + "|" + d["fixture"]["away"]).lower():
                continue
            out.append(d)
        return {"total": len(out), "items": out[:limit], "disclaimer": "VIRTUAL bets — simulation only, no real money."}


@app.get("/api/analytics")
def analytics():
    sm = summary()
    with session_scope() as s:
        bt = s.scalars(select(BacktestRun).order_by(BacktestRun.id.desc())).first()
        models = [{"id": m.id, "name": m.name, "version": m.version, "params": m.params, "metrics": m.metrics,
                   "created_at": iso(m.created_at), "active": m.active} for m in s.scalars(select(ModelVersion))]
    return {"live": sm, "backtest": bt.results if bt else None, "backtest_at": iso(bt.created_at) if bt else None,
            "models": models}


@app.get("/api/sources")
def sources():
    with session_scope() as s:
        ds = s.scalars(select(DataSource).order_by(DataSource.id)).all()
        n_odds = s.scalar(select(func.count(OddsObservation.id)))
        n_fx = s.scalar(select(func.count(Fixture.id)))
        n_stats = s.scalar(select(func.count(MatchStats.id)))
        comps = s.scalars(select(Competition).order_by(Competition.priority, Competition.code)).all()
        return {
            "providers": [{"key": d.key, "name": d.name, "kind": d.kind, "base_url": d.base_url, "license": d.license_note,
                           "requires_key": d.requires_key, "configured": d.configured, "reliability": d.reliability,
                           "status": d.status, "last_attempt_at": iso(d.last_attempt_at), "last_success_at": iso(d.last_success_at),
                           "last_error_at": iso(d.last_error_at), "last_error": d.last_error, "quota": d.quota_info,
                           "requests_total": d.requests_total, "records_total": d.records_total,
                           "freshness_hours": round((utcnow() - d.last_success_at).total_seconds() / 3600, 1) if d.last_success_at else None}
                          for d in ds],
            "totals": {"fixtures": n_fx, "odds_snapshots": n_odds, "match_stats": n_stats},
            "coverage": [{"code": c.code, "name": c.name, "region": c.region, "country": c.country, "eligible": c.eligible,
                          "priority": c.priority, "coverage": c.coverage, "updated_at": iso(c.coverage_updated_at)} for c in comps],
        }


@app.get("/api/system")
def system():
    with session_scope() as s:
        runs = s.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(40)).all()
        errors = s.scalars(select(SystemLog).where(SystemLog.level.in_(["WARNING", "ERROR"])).order_by(SystemLog.id.desc()).limit(40)).all()
        db_size = settings.db_path.stat().st_size if settings.db_path.exists() else 0
        backups = sorted(settings.backup_dir.glob("fil-*.db.gz"))
        counts = {t: s.scalar(text(f"SELECT COUNT(*) FROM {t}")) for t in
                  ("fixtures", "odds_observations", "predictions", "value_assessments", "virtual_bets", "settlements",
                   "bankroll_transactions", "teams", "reports", "system_logs")}
    sched = scheduler.status() if scheduler.running() else []
    for j in sched:
        j["last_success"] = iso(j["last_success"])
    return {
        "backend": "ok", "version": __version__, "scheduler_running": scheduler.running(), "jobs": sched,
        "database": {"path": str(settings.db_path), "size_mb": round(db_size / 1e6, 2), "counts": counts,
                     "backups": [{"file": b.name, "size_mb": round(b.stat().st_size / 1e6, 2)} for b in backups[-10:]]},
        "recent_runs": [{"id": r.id, "job": r.job, "status": r.status, "started_at": iso(r.started_at),
                         "finished_at": iso(r.finished_at), "duration_s": round((r.finished_at - r.started_at).total_seconds(), 1) if r.finished_at else None,
                         "summary": r.summary, "error": (r.error or "")[:1500] or None} for r in runs],
        "recent_errors": [{"ts": iso(e.ts), "level": e.level, "component": e.component, "message": e.message[:500]} for e in errors],
    }


@app.get("/api/reports")
def get_reports(kind: str | None = None, limit: int = 20):
    with session_scope() as s:
        q = select(Report)
        if kind:
            q = q.where(Report.kind == kind)
        return [{"id": r.id, "kind": r.kind, "created_at": iso(r.created_at), "period_start": iso(r.period_start),
                 "period_end": iso(r.period_end), "content": r.content, "markdown": r.markdown}
                for r in s.scalars(q.order_by(Report.id.desc()).limit(limit))]


@app.get("/api/meta")
def meta():
    with session_scope() as s:
        comps = [{"code": c.code, "name": c.name, "region": c.region} for c in s.scalars(select(Competition).order_by(Competition.code))]
        models = [{"id": m.id, "label": f"{m.name} {m.version}"} for m in s.scalars(select(ModelVersion))]
    return {"competitions": comps, "models": models, "value_rules": vars(settings.value), "risk_rules": vars(settings.risk),
            "settlement_rules": SETTLEMENT_RULES, "bookmakers": BOOKMAKER_LABELS, "display_timezone": settings.display_tz,
            "disclaimer": "Simulation only. No real-money betting, no bookmaker accounts, no transactions."}


@app.post("/api/admin/run/{job}")
def admin_run(job: str, x_admin_token: str = Header(default="")):
    if not settings.admin_token:
        raise HTTPException(403, "admin endpoints disabled (FIL_ADMIN_TOKEN not set)")
    if not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(401, "invalid admin token")
    if job not in JOBS:
        raise HTTPException(404, f"unknown job; choose one of {sorted(JOBS)}")
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return {"started": job}


# ------------------------------------------------------------------ static dashboard
if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        f = STATIC / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
