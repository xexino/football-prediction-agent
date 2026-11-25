"""Engine B pipeline: train -> predict upcoming fixtures -> AI report -> independent virtual bets -> evaluate."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta

import numpy as np
from sqlalchemy import func, select

from ..db import (Competition, EBEvaluation, EBModelVersion, EBPrediction, EBValidationRun, Fixture, MatchStats,
                  OddsObservation, Prediction, StandingSnapshot, Team, log, session_scope)
from ..models.markets import devig
from ..timeutil import utcnow
from . import betting
from .features import FEATURE_NAMES, MIN_HISTORY, build_rows, load_history
from .insights import build_report
from .model import MODEL_NAME, MODEL_VERSION, EngineBModel

_CACHE: dict = {}
DESCRIPTION = ("Feature-based Poisson GLMs (EWMA attack/defence of goals, shots on target, corners, cards, fouls; "
               "own Elo; rest days; league means) per count market, Dixon-Coles low-score correction for goals, "
               "negative-binomial totals for corners/cards. Independent of Engine A.")


def model_version_id() -> int:
    with session_scope() as s:
        mv = s.scalars(select(EBModelVersion).where(EBModelVersion.name == MODEL_NAME,
                                                    EBModelVersion.version == MODEL_VERSION)).first()
        if mv is None:
            mv = EBModelVersion(name=MODEL_NAME, version=MODEL_VERSION, description=DESCRIPTION,
                                params={"alpha": 1e-3, "ewma_alpha": 0.12, "window_days": 1100, "min_history": MIN_HISTORY,
                                        "elo_k": 18, "elo_home": 55, "risk": betting.RISK.__dict__ | {}},
                                features=FEATURE_NAMES["goals"])
            s.add(mv)
            s.flush()
        return mv.id


def get_model(force: bool = False):
    with session_scope() as s:
        n = s.scalar(select(func.count(Fixture.id)).where(Fixture.status == "finished"))
    now = utcnow()
    c = _CACHE.get("m")
    if c and not force and _CACHE["n"] == n and now - _CACHE["at"] < timedelta(hours=6):
        return c
    hist = load_history(before=now)
    rows, state = build_rows(hist)
    model = EngineBModel().fit(rows, now)
    _CACHE.update(m=(model, state, now), n=n, at=now)
    log("INFO", "engine_b", f"trained on {len(rows)} matches; markets ready: {sorted({m for m, _ in model.glm})}")
    return _CACHE["m"]


def _snaps(s, fixture_id, now) -> dict:
    out = {}
    for o in s.scalars(select(OddsObservation).where(OddsObservation.fixture_id == fixture_id, OddsObservation.kind == "pre_match",
                                                     OddsObservation.retrieved_at <= now).order_by(OddsObservation.retrieved_at)):
        out[o.bookmaker] = o
    return out


def market_1x2(snaps: dict):
    for b in ("BFE", "PS", "Avg", "B365"):
        o = snaps.get(b)
        if o is not None and o.home and o.draw and o.away:
            p = devig([o.home, o.draw, o.away])
            return {"home": p[0], "draw": p[1], "away": p[2], "bookmaker": b}
    return None


def quality_b(feat: dict, snaps: dict, table: dict) -> tuple[float, dict]:
    q = {
        "history": 30 * min(1.0, min(feat["n_home"], feat["n_away"]) / 30),
        "shot_and_set_piece_stats": 20 * (feat.get("h_sot_att") is not None and feat.get("a_sot_def") is not None),
        "corner_card_history": 10 * (feat.get("h_corners_att") is not None),
        "odds": 15 * bool(snaps),
        "league_table": 5 * bool(table.get("home") and table.get("away")),
        "recency": 10 * (feat.get("rest_home") is not None and feat.get("rest_home") <= 30
                         and feat.get("rest_away") is not None and feat.get("rest_away") <= 30),
        "team_news": 0.0,
        "league_volume": 10 * min(1.0, feat["league_matches"] / 600),
    }
    q = {k: round(float(v), 1) for k, v in q.items()}
    return round(sum(q.values()), 1), q


def confidence_b(feat: dict, engine_a: dict | None, comp_skill: float | None, quality: float) -> float:
    sample = min(1.0, min(feat["n_home"], feat["n_away"]) / 40)
    agree = 0.5 if engine_a is None else max(0.0, 1 - engine_a["_gap"] / 0.25)
    skill = 0.5 if comp_skill is None else max(0.0, min(1.0, 0.5 + comp_skill * 10))
    return round(100 * (0.3 * quality / 100 + 0.25 * sample + 0.25 * agree + 0.2 * skill), 1)


def _comp_skill() -> dict:
    """Validation log-loss improvement over the naive baseline, per competition (latest run)."""
    with session_scope() as s:
        r = s.scalars(select(EBValidationRun).order_by(EBValidationRun.id.desc())).first()
        if r is None:
            return {}
        out = {}
        for comp, m in (r.results.get("by_competition") or {}).items():
            b, base = (m.get("engine_b") or {}).get("log_loss"), (m.get("naive") or {}).get("log_loss")
            if b and base:
                out[comp] = base - b
        return out


def _h2h(s, home, away, before, limit=6):
    rows = s.scalars(select(Fixture).where(Fixture.status == "finished", Fixture.kickoff_utc < before,
                                           ((Fixture.home_team_id == home) & (Fixture.away_team_id == away)) |
                                           ((Fixture.home_team_id == away) & (Fixture.away_team_id == home)))
                     .order_by(Fixture.kickoff_utc.desc()).limit(limit)).all()
    out = []
    for f in rows:
        hg, ag = (f.home_goals, f.away_goals) if f.home_team_id == home else (f.away_goals, f.home_goals)
        out.append({"date": f.kickoff_utc.strftime("%Y-%m-%d"), "score_home_perspective": f"{hg}-{ag}",
                    "winner": "home_team" if hg > ag else "away_team" if ag > hg else "draw"})
    return out


def _table(s, comp_id, home, away):
    out = {}
    for side, tid in (("home", home), ("away", away)):
        r = s.scalars(select(StandingSnapshot).where(StandingSnapshot.competition_id == comp_id, StandingSnapshot.team_id == tid)
                      .order_by(StandingSnapshot.snapshot_date.desc())).first()
        if r:
            out[side] = {"position": r.position, "points": r.points, "played": r.played, "as_of": r.snapshot_date}
    return out


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return None if math.isnan(v) or math.isinf(v) else round(v, 5)
    if isinstance(o, np.integer):
        return int(o)
    return o


def predict_upcoming(horizon_days: int = 7) -> dict:
    model, state, trained_at = get_model()
    mv = model_version_id()
    now = utcnow()
    skill = _comp_skill()
    from ..config import settings

    live_ok = bool(settings.api_football_key)
    out = {"fixtures": 0, "predicted": 0, "revisions": 0, "unchanged": 0, "insufficient_data": 0, "bets": 0}
    with session_scope() as s:
        betting.ensure_bankroll(s)
        comps = {c.id: c for c in s.scalars(select(Competition))}
        teams = {t.id: t.name for t in s.scalars(select(Team))}
        fixtures = s.scalars(select(Fixture).where(Fixture.status == "scheduled", Fixture.kickoff_utc > now + timedelta(minutes=10),
                                                   Fixture.kickoff_utc < now + timedelta(days=horizon_days))).all()
        for fx in fixtures:
            out["fixtures"] += 1
            comp = comps[fx.competition_id]
            feat = state.features(comp.code, fx.home_team_id, fx.away_team_id, fx.kickoff_utc, fx.neutral)
            pred = model.predict(feat)
            if not pred["markets"]:
                out["insufficient_data"] += 1
                continue
            snaps = _snaps(s, fx.id, now)
            mk1 = market_1x2(snaps)
            a = s.scalars(select(Prediction).where(Prediction.fixture_id == fx.id).order_by(Prediction.revision.desc())).first()
            engine_a = None
            if a is not None:
                engine_a = dict(a.probs["1X2"])
                engine_a["_gap"] = max(abs(engine_a[k] - pred["markets"]["1X2"][k]) for k in ("home", "draw", "away"))
            table = _table(s, fx.competition_id, fx.home_team_id, fx.away_team_id)
            quality, qb = quality_b(feat, snaps, table)
            conf = confidence_b(feat, engine_a, skill.get(comp.code), quality)
            report = build_report(home=teams[fx.home_team_id], away=teams[fx.away_team_id], competition=comp.name,
                                  markets=pred["markets"], features=feat,
                                  form={"home": state.form(fx.home_team_id), "away": state.form(fx.away_team_id)},
                                  h2h=_h2h(s, fx.home_team_id, fx.away_team_id, fx.kickoff_utc), table=table,
                                  engine_a=({k: v for k, v in engine_a.items() if k != "_gap"} if engine_a else None),
                                  market_1x2=({k: v for k, v in mk1.items() if k != "bookmaker"} if mk1 else None),
                                  unavailable=pred["unavailable"], quality=quality, confidence=conf, live_available=live_ok)
            report["quality_breakdown"] = qb
            from ..pipeline import _renormalise

            markets = _renormalise(_clean(pred["markets"]))  # exact sums after rounding (audit 2026-11-25)
            ihash = hashlib.sha1(json.dumps({"mv": mv, "x": {k: round(v, 3) for k, v in markets["1X2"].items()},
                                             "odds": sorted(o.id for o in snaps.values())}, sort_keys=True).encode()).hexdigest()
            last = s.scalars(select(EBPrediction).where(EBPrediction.fixture_id == fx.id).order_by(EBPrediction.revision.desc())).first()
            if last is not None:
                if last.inputs_hash == ihash:
                    out["unchanged"] += 1
                    continue
                moved = max(abs(markets["1X2"][k] - last.markets["1X2"][k]) for k in ("home", "draw", "away"))
                if moved < 0.02 and last.model_version_id == mv and sorted(last.features.get("_odds_ids", [])) == sorted(o.id for o in snaps.values()):
                    out["unchanged"] += 1
                    continue
            feat_snapshot = _clean({k: v for k, v in feat.items()}) | {"_odds_ids": sorted(o.id for o in snaps.values()),
                                                                     "_trained_at": trained_at.isoformat()}
            p = EBPrediction(fixture_id=fx.id, model_version_id=mv, created_at=now, kickoff_utc=fx.kickoff_utc,
                             data_cutoff=trained_at, revision=0 if last is None else last.revision + 1, markets=markets,
                             score_matrix=[[round(float(v), 5) for v in row[:8]] for row in pred["matrix"][:8]],
                             features=feat_snapshot, confidence=conf, data_quality=quality, unavailable=pred["unavailable"],
                             report=_clean(report), inputs_hash=ihash)
            s.add(p)
            s.flush()
            out["predicted" if last is None else "revisions"] += 1
            already = s.scalar(select(func.count()).select_from(betting.EBBet).where(betting.EBBet.fixture_id == fx.id))
            for c in betting.choose(betting.candidates(pred["markets"], snaps, quality, conf), already):
                if betting.place(s, prediction=p, fixture=fx, cand=c, quality=quality):
                    out["bets"] += 1
    return out


def evaluate() -> dict:
    """Score original (revision 0) Engine B predictions once the verified result exists."""
    n = 0
    with session_scope() as s:
        done = set(s.scalars(select(EBEvaluation.prediction_id)))
        rows = s.execute(select(EBPrediction, Fixture).join(Fixture, Fixture.id == EBPrediction.fixture_id).where(
            EBPrediction.revision == 0, Fixture.status == "finished", Fixture.home_goals.is_not(None))).all()
        stats = {m.fixture_id: m for m in s.scalars(select(MatchStats).where(MatchStats.source == "football_data_uk",
                                                                            MatchStats.fixture_id.in_([f.id for _, f in rows])))}
        for p, f in rows:
            if p.id in done:
                continue
            hg, ag = f.home_goals, f.away_goals
            res = "home" if hg > ag else "draw" if hg == ag else "away"
            x = p.markets["1X2"]
            m = {"logloss_1x2": -math.log(max(x[res], 1e-9)),
                 "brier_1x2": sum((x[k] - (k == res)) ** 2 for k in x), "correct_1x2": max(x, key=x.get) == res,
                 "logloss_ou25": -math.log(max(p.markets["OU25"]["over" if hg + ag > 2.5 else "under"], 1e-9)),
                 "logloss_btts": -math.log(max(p.markets["BTTS"]["yes" if hg and ag else "no"], 1e-9)),
                 "goals_abs_err": abs(p.markets["EXPECTED_GOALS"]["total"] - (hg + ag))}
            st = stats.get(f.id)
            for metric, attr in (("CORNERS", "corners"), ("YELLOWS", "yellow")):
                if metric in p.markets and st is not None and getattr(st, f"home_{attr}") is not None:
                    actual = getattr(st, f"home_{attr}") + getattr(st, f"away_{attr}")
                    lo, hi = p.markets[metric]["interval_80"]
                    m[f"{attr}_abs_err"] = abs(p.markets[metric]["expected"]["total"] - actual)
                    m[f"{attr}_in_80"] = lo <= actual <= hi
            s.add(EBEvaluation(prediction_id=p.id, metrics=_clean(m)))
            n += 1
    return {"evaluated": n}
