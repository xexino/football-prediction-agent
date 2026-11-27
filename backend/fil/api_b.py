"""Engine B (AI Match Insights) API — read-only, separate router; Engine A endpoints are untouched."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

import numpy as np
from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from .db import (ModelVersion, Competition, DataSource, EBBankrollTransaction, EBBet, EBEvaluation, EBLiveEvent, EBLiveSnapshot,
                 EBModelVersion, EBPrediction, EBSettlement, EBValidationRun, Fixture, OddsObservation, Prediction, Team,
                 session_scope)
from .engine_b.features import MIN_HISTORY
from .timeutil import iso, rome, utcnow

router = APIRouter()


def _maps(s):
    return ({t.id: t.name for t in s.scalars(select(Team))}, {c.id: c for c in s.scalars(select(Competition))})


def _fx(f, teams, comps):
    c = comps[f.competition_id]
    return {"id": f.id, "competition": c.code, "competition_name": c.name, "country": c.country, "region": c.region,
            "home": teams.get(f.home_team_id), "away": teams.get(f.away_team_id), "kickoff_utc": iso(f.kickoff_utc),
            "kickoff_rome": rome(f.kickoff_utc), "status": f.status,
            "score": None if f.home_goals is None else f"{f.home_goals}-{f.away_goals}",
            "coverage_status": (c.coverage or {}).get("coverage_status", "UNKNOWN")}


UEFA_CLUB_COMPS = {"UCL", "UEL", "UECL"}


def cross_league_low_confidence(comp_code: str, features: dict | None) -> bool:
    """Display-only warning (council cycles 2026-11-26/27): in UEFA club competitions Engine B's ratings mix scales
    from different leagues, and UEFA teams often carry separate ids with no domestic history. A prediction is flagged
    when either side has fewer than MIN_HISTORY domestic-league matches in B's state. Probabilities and bets are
    untouched; predictions stored before this field existed count as 0 domestic matches (flagged)."""
    if comp_code not in UEFA_CLUB_COMPS:
        return False
    f = features or {}
    return min(f.get("n_dom_home", 0) or 0, f.get("n_dom_away", 0) or 0) < MIN_HISTORY


def _summary(p: EBPrediction | None):
    if p is None:
        return None
    m = p.markets
    return {"id": p.id, "revision": p.revision, "created_at": iso(p.created_at), "x12": m["1X2"],
            "xg": m["EXPECTED_GOALS"], "top_scores": dict(list(m["CORRECT_SCORE_TOP"].items())[:3]), "btts": m["BTTS"]["yes"],
            "over25": m["OU25"]["over"], "over15": m["OU15"]["over"],
            "corners": (m.get("CORNERS") or {}).get("expected"), "cards": (m.get("YELLOWS") or {}).get("expected"),
            "confidence": p.confidence, "data_quality": p.data_quality,
            "headline": (p.report or {}).get("sections", {}).get("assessment")}


def _market(s, fid):
    snaps = {}
    for o in s.scalars(select(OddsObservation).where(OddsObservation.fixture_id == fid, OddsObservation.kind == "pre_match")
                       .order_by(OddsObservation.retrieved_at)):
        snaps[o.bookmaker] = o
    from .engine_b.pipeline import market_1x2

    return market_1x2(snaps), snaps


def _latest(rows, key):
    out = {}
    for r in rows:
        out[getattr(r, key)] = r
    return out


@router.get("/api/insights")
def insights(days_back: int = 3, days_forward: int = 7):
    now = utcnow()
    with session_scope() as s:
        teams, comps = _maps(s)
        fixtures = s.scalars(select(Fixture).where(Fixture.kickoff_utc > now - timedelta(days=days_back),
                                                   Fixture.kickoff_utc < now + timedelta(days=days_forward))
                             .order_by(Fixture.kickoff_utc)).all()
        ids = [f.id for f in fixtures]
        bp = _latest(s.scalars(select(EBPrediction).where(EBPrediction.fixture_id.in_(ids)).order_by(EBPrediction.revision)), "fixture_id")
        ap = _latest(s.scalars(select(Prediction).where(Prediction.fixture_id.in_(ids)).order_by(Prediction.revision)), "fixture_id")
        live = _latest(s.scalars(select(EBLiveSnapshot).where(EBLiveSnapshot.fixture_id.in_(ids)).order_by(EBLiveSnapshot.id)), "fixture_id")
        bets = {b.fixture_id for b in s.scalars(select(EBBet).where(EBBet.fixture_id.in_(ids)))}
        items = []
        for f in fixtures:
            p = bp.get(f.id)
            if p is None and f.kickoff_utc > now and not ap.get(f.id):
                # unpredicted upcoming fixture: list it with its coverage status only
                pass
            lv = live.get(f.id)
            # a match is shown as "live" only while snapshots keep arriving (council LV-2: was 3 h after the last one)
            recent_live = lv is not None and now - lv.created_at < timedelta(minutes=45)
            phase = ("finished" if f.status == "finished" else
                     "postponed" if f.status in ("postponed", "cancelled", "abandoned") else
                     "live" if recent_live and lv.status in ("live", "halftime") and lv.data_label != "STALE" else
                     "upcoming" if f.kickoff_utc > now else "awaiting_result")
            if p is None and phase != "live" and comps[f.competition_id].code in ("INTFR",):
                continue
            mk, _ = _market(s, f.id) if p is not None else (None, None)
            items.append({**_fx(f, teams, comps), "phase": phase, "engine_b": _summary(p),
                          "cross_league_low_confidence": p is not None and cross_league_low_confidence(
                              comps[f.competition_id].code, p.features),
                          "engine_a": ap[f.id].probs["1X2"] if f.id in ap else None, "market": mk,
                          "live": None if lv is None else {"label": lv.data_label, "minute": lv.minute, "status": lv.status,
                                                           "score": None if lv.home_goals is None else f"{lv.home_goals}-{lv.away_goals}",
                                                           "provider": lv.provider, "at": iso(lv.created_at)},
                          "has_selection": f.id in bets})
        return {"generated_at": iso(now), "items": [i for i in items if i["engine_b"] or i["phase"] == "live" or i["engine_a"]
                                                     or i["coverage_status"] not in ("FULL COVERAGE", "PARTIAL COVERAGE")]}


@router.get("/api/insights/{fixture_id}")
def insight_detail(fixture_id: int):
    with session_scope() as s:
        f = s.get(Fixture, fixture_id)
        if f is None:
            raise HTTPException(404)
        teams, comps = _maps(s)
        preds = s.scalars(select(EBPrediction).where(EBPrediction.fixture_id == f.id).order_by(EBPrediction.revision)).all()
        a = s.scalars(select(Prediction).where(Prediction.fixture_id == f.id).order_by(Prediction.revision.desc())).first()
        mk, snaps = _market(s, f.id)
        snaps_out = {b: {"home": o.home, "draw": o.draw, "away": o.away, "over25": o.over25, "under25": o.under25,
                         "retrieved_at": iso(o.retrieved_at)} for b, o in snaps.items()}
        live = s.scalars(select(EBLiveSnapshot).where(EBLiveSnapshot.fixture_id == f.id).order_by(EBLiveSnapshot.id)).all()
        events = s.scalars(select(EBLiveEvent).where(EBLiveEvent.fixture_id == f.id).order_by(EBLiveEvent.minute)).all()
        bets = s.scalars(select(EBBet).where(EBBet.fixture_id == f.id)).all()
        evals = {e.prediction_id: e.metrics for e in s.scalars(select(EBEvaluation).where(
            EBEvaluation.prediction_id.in_([p.id for p in preds])))}
        latest = preds[-1] if preds else None
        mv = s.get(EBModelVersion, latest.model_version_id) if latest else None
        return {
            "fixture": _fx(f, teams, comps),
            "model": None if mv is None else {"name": mv.name, "version": mv.version, "description": mv.description},
            "prediction": None if latest is None else {
                "id": latest.id, "revision": latest.revision, "created_at": iso(latest.created_at),
                "data_cutoff": iso(latest.data_cutoff), "markets": latest.markets, "score_matrix": latest.score_matrix,
                "unavailable": latest.unavailable, "report": latest.report, "confidence": latest.confidence,
                "data_quality": latest.data_quality, "features": latest.features,
                "cross_league_low_confidence": cross_league_low_confidence(comps[f.competition_id].code, latest.features)},
            "history": [{"id": p.id, "revision": p.revision, "created_at": iso(p.created_at), "x12": p.markets["1X2"],
                         "xg": p.markets["EXPECTED_GOALS"], "evaluation": evals.get(p.id)} for p in preds],
            "engine_a": None if a is None else {"x12": a.probs["1X2"], "exp_goals": [a.exp_home_goals, a.exp_away_goals],
                                                "decision": a.decision, "created_at": iso(a.created_at), "confidence": a.confidence,
                                                "revision": a.revision,
                                                "model": (lambda mv: f"{mv.name} {mv.version}" if mv else None)(s.get(ModelVersion, a.model_version_id))},
            "market": mk, "odds": snaps_out,
            "live": [{"at": iso(l.created_at), "provider": l.provider, "label": l.data_label, "status": l.status, "minute": l.minute,
                      "minute_source": l.minute_source, "score": None if l.home_goals is None else f"{l.home_goals}-{l.away_goals}",
                      "stats": l.stats, "freshness_s": l.freshness_s, "probs": l.probs} for l in live],
            "events": [{"minute": e.minute, "type": e.event_type, "side": e.side, "player": e.player, "detail": e.detail,
                        "provider": e.provider} for e in events],
            "selections": [{"market": b.market, "selection": b.selection, "price": b.price, "stake": b.stake, "ev": b.ev,
                            "status": b.status, "profit": b.profit, "reason": b.reason, "created_at": iso(b.created_at)} for b in bets],
        }


def _perf(bets):
    settled = [b for b in bets if b.status != "pending"]
    staked = sum(b.stake for b in settled)
    ret = sum(b.payout or 0 for b in settled)
    wins = sum(1 for b in settled if b.status in ("won", "half_won"))
    clv = [b.clv for b in settled if b.clv is not None]
    return {"bets": len(bets), "settled": len(settled), "pending": len(bets) - len(settled), "won": wins,
            "staked": round(staked, 2), "profit": round(ret - staked, 2), "roi": round((ret - staked) / staked, 4) if staked else None,
            "win_rate": round(wins / len(settled), 4) if settled else None,
            "avg_clv": round(float(np.mean(clv)), 4) if clv else None}


@router.get("/api/engine_b/performance")
def performance():
    with session_scope() as s:
        teams, comps = _maps(s)
        bets = s.scalars(select(EBBet).order_by(EBBet.created_at)).all()
        txs = s.scalars(select(EBBankrollTransaction).order_by(EBBankrollTransaction.id)).all()
        fx = {f.id: f for f in s.scalars(select(Fixture).where(Fixture.id.in_([b.fixture_id for b in bets])))}
        mvs = {m.id: f"{m.name} {m.version}" for m in s.scalars(select(EBModelVersion))}
        group = lambda key: {k: _perf(v) for k, v in _groupby(bets, key).items()}  # noqa: E731
        evals = s.execute(select(EBEvaluation, EBPrediction).join(EBPrediction, EBPrediction.id == EBEvaluation.prediction_id)).all()
        ev = defaultdict(list)
        for e, p in evals:
            for k, v in e.metrics.items():
                ev[k].append(float(v))
        vr = s.scalars(select(EBValidationRun).order_by(EBValidationRun.id.desc())).first()
        n_pred = s.scalar(select(func.count(EBPrediction.id)))
        return {
            "bankroll": {"start": txs[0].amount if txs else 100.0, "current": txs[-1].balance_after if txs else 500.0,
                         # capital = initial + top-ups (owner decision 2026-11-25: €500); open = stakes of pending bets
                         "capital": round(sum(t.amount for t in txs if t.tx_type in ("initial", "top_up")), 2) if txs else 500.0,
                         "open": round(sum(b.stake for b in bets if b.status == "pending"), 2),
                         "history": [{"t": iso(t.created_at), "balance": t.balance_after, "type": t.tx_type} for t in txs]},
            "overall": _perf(bets), "by_market": group(lambda b: b.market),
            "by_competition": group(lambda b: comps[fx[b.fixture_id].competition_id].code),
            "by_mode": group(lambda b: b.mode), "by_model": group(lambda b: mvs.get(b.model_version_id, "?")),
            "ledger": [{"id": b.id, "created_at": iso(b.created_at), "match": f"{teams.get(fx[b.fixture_id].home_team_id)} – "
                        f"{teams.get(fx[b.fixture_id].away_team_id)}", "competition": comps[fx[b.fixture_id].competition_id].name,
                        "market": b.market, "selection": b.selection, "price": b.price, "stake": b.stake, "ev": b.ev,
                        "status": b.status, "profit": b.profit, "clv": b.clv, "reason": b.reason, "mode": b.mode} for b in reversed(bets)],
            "prediction_metrics": {k: {"mean": round(float(np.mean(v)), 4), "n": len(v)} for k, v in ev.items()},
            "predictions_total": n_pred,
            "validation": None if vr is None else vr.results, "validation_at": iso(vr.created_at) if vr else None,
            "models": [{"name": m.name, "version": m.version, "description": m.description, "params": m.params,
                        "features": m.features, "created_at": iso(m.created_at)} for m in s.scalars(select(EBModelVersion))],
            "disclaimer": "Engine B virtual bankroll — simulation only; separate from Engine A.",
        }


def _groupby(items, key):
    g = defaultdict(list)
    for i in items:
        g[key(i)].append(i)
    return g


@router.get("/api/engine_compare")
def compare(days_back: int = 30):
    now = utcnow()
    with session_scope() as s:
        teams, comps = _maps(s)
        bp = _latest(s.scalars(select(EBPrediction).where(EBPrediction.revision == 0,
                                                          EBPrediction.kickoff_utc > now - timedelta(days=days_back))), "fixture_id")
        ap = {}
        for p in s.scalars(select(Prediction).where(Prediction.fixture_id.in_(list(bp))).order_by(Prediction.revision.desc())):
            ap[p.fixture_id] = p  # revision 0 last -> original kept
        fxs = {f.id: f for f in s.scalars(select(Fixture).where(Fixture.id.in_(list(bp))))}
        rows, agg, agg_all = [], defaultdict(list), defaultdict(list)
        for fid, b in bp.items():
            f = fxs[fid]
            a = ap.get(fid)
            mk, _ = _market(s, fid)
            res = None
            if f.status == "finished" and f.home_goals is not None:
                res = "home" if f.home_goals > f.away_goals else "draw" if f.home_goals == f.away_goals else "away"
            r = {**_fx(f, teams, comps), "engine_b": b.markets["1X2"], "engine_a": a.probs["1X2"] if a else None,
                 "market": mk, "result": res}
            if a:
                r["disagreement"] = round(max(abs(a.probs["1X2"][k] - b.markets["1X2"][k]) for k in ("home", "draw", "away")), 4)
            if res:
                srcs = (("engine_b", b.markets["1X2"]), ("engine_a", a.probs["1X2"] if a else None), ("market", mk))
                for name, pr in srcs:
                    if pr:
                        ll = -math.log(max(pr[res], 1e-9))
                        r[f"logloss_{name}"] = round(ll, 4)
                        agg_all[name].append(ll)
                if all(pr for _, pr in srcs):  # like-for-like: only matches every source predicted
                    for name, _ in srcs:
                        agg[name].append(r[f"logloss_{name}"])
            rows.append(r)
        rows.sort(key=lambda r: r["kickoff_utc"], reverse=True)
        summ = lambda d: {k: {"mean": round(float(np.mean(v)), 4), "n": len(v)} for k, v in d.items()}
        return {"rows": rows, "live_log_loss": summ(agg), "live_log_loss_all": summ(agg_all),
                "note": "Original (first) predictions of each engine. live_log_loss compares only matches that Engine A, "
                        "Engine B and the market all predicted (same n); live_log_loss_all uses every available match."}


@router.get("/api/coverage_matrix")
def coverage_matrix():
    from .engine_b.live import providers

    with session_scope() as s:
        comps = s.scalars(select(Competition).order_by(Competition.region, Competition.priority, Competition.name)).all()
        ds = {d.key: d for d in s.scalars(select(DataSource))}
        live_now = s.scalar(select(func.count(EBLiveSnapshot.id)).where(EBLiveSnapshot.created_at > utcnow() - timedelta(hours=24)))
        return {
            "competitions": [{"code": c.code, "name": c.name, "country": c.country, "region": c.region,
                              "status": (c.coverage or {}).get("coverage_status", "UNAVAILABLE"),
                              "live": (c.coverage or {}).get("live", "no live source"),
                              "history": (c.coverage or {}).get("historical_matches", 0),
                              "upcoming": (c.coverage or {}).get("upcoming_14d", 0),
                              "odds": (c.coverage or {}).get("odds_history_share", 0),
                              "stats": (c.coverage or {}).get("stats_share", 0),
                              "sources": sorted((c.sources or {}).keys())} for c in comps],
            "live_providers": [{"name": p.name, "configured": p.configured, "priority": p.priority, "capabilities": p.capabilities,
                                "status": (ds.get(p.name).status if ds.get(p.name) else "unknown"),
                                "last_success": iso(ds.get(p.name).last_success_at) if ds.get(p.name) else None}
                               for p in providers()],
            "live_snapshots_24h": live_now,
            "statuses": ["FULL COVERAGE", "PARTIAL COVERAGE", "FIXTURES AND RESULTS ONLY", "LIVE SCORES ONLY",
                         "COVERAGE ONLY — NOT ENOUGH DATA FOR PREDICTIONS", "UNAVAILABLE"],
        }
