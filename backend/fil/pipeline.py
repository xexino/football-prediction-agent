"""End-to-end prediction pipeline: model training -> predictions -> value -> simulated bets."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta

from sqlalchemy import func, select

from .betting import ensure_bankroll, place_bet
from .config import settings
from .db import (Team, Competition, Fixture, MatchStats, ModelVersion, OddsObservation, Prediction, TeamAlias, TeamNews,
                 ValueAssessment, VirtualBet, log, session_scope)
from .models.engine import MODEL_NAME, MODEL_VERSION, PARAMS, Engine, load_matches
from .quality import confidence as confidence_score
from .quality import score as quality_score
from .value import assess, book_dispersion, select_bets
from .models.markets import devig, overround
from .timeutil import utcnow

_ENGINE: dict = {}
HORIZON_DAYS = 7
NO_BET_MSG = "NO BET — no sufficiently reliable value opportunity identified."


def model_version_id() -> int:
    with session_scope() as s:
        mv = s.scalars(select(ModelVersion).where(ModelVersion.name == MODEL_NAME,
                                                  ModelVersion.version == MODEL_VERSION)).first()
        if mv is None:
            mv = ModelVersion(name=MODEL_NAME, version=MODEL_VERSION, description=PARAMS["description"],
                              params={k: v for k, v in PARAMS.items() if k != "description"})
            s.add(mv)
            s.flush()
        return mv.id


def get_engine(force: bool = False) -> Engine:
    """Train (or reuse) the engine. Retrained when new results arrived or after 6 hours."""
    with session_scope() as s:
        n_finished = s.scalar(select(func.count(Fixture.id)).where(Fixture.status == "finished"))
    now = utcnow()
    e = _ENGINE.get("engine")
    if (not force and e is not None and _ENGINE.get("n") == n_finished
            and now - _ENGINE["at"] < timedelta(hours=6)):
        return e
    matches = load_matches(before=now)
    e = Engine().build(matches, now, prev=e)
    _ENGINE.update(engine=e, n=n_finished, at=now)
    log("INFO", "engine", f"trained on {len(matches)} matches; DC fitted for {len(e.dc)} competitions")
    return e


def _latest_snapshots(s, fixture_id: int, now) -> dict:
    """Most recent pre-match snapshot per bookmaker retrieved before `now` (never mixes timestamps
    within one bookmaker's row)."""
    rows = s.scalars(select(OddsObservation).where(
        OddsObservation.fixture_id == fixture_id, OddsObservation.kind == "pre_match",
        OddsObservation.retrieved_at <= now).order_by(OddsObservation.retrieved_at)).all()
    snaps = {}
    for o in rows:
        snaps[o.bookmaker] = o
    return snaps


def _name_confidence(s, fx) -> float:
    confs = s.execute(select(TeamAlias.confidence).where(TeamAlias.team_id.in_([fx.home_team_id, fx.away_team_id]))).scalars().all()
    return min(confs) if confs else 1.0


def _stats_shares(s, comp_id: int, team_ids: list[int]) -> tuple[float, float]:
    rows = s.execute(select(MatchStats.home_xg, MatchStats.home_shots).join(Fixture, Fixture.id == MatchStats.fixture_id).where(
        Fixture.competition_id == comp_id, (Fixture.home_team_id.in_(team_ids)) | (Fixture.away_team_id.in_(team_ids)))
        .order_by(Fixture.kickoff_utc.desc()).limit(20)).all()
    if not rows:
        return 0.0, 0.0
    return (sum(1 for r in rows if r[0] is not None) / len(rows), sum(1 for r in rows if r[1] is not None) / len(rows))


def _hash(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, float):
        return None if math.isnan(x) else round(x, 5)
    return x


_COMPLEMENTS = ({"home", "draw", "away"}, {"over", "under"}, {"yes", "no"})


def _renormalise(markets: dict) -> dict:
    """After rounding to 5 dp, a complementary distribution can sum to 1 ± 1e-5 (CI failure F-08, 2026-11-23).
    Put the rounding residue on the largest outcome so every distribution sums to exactly 1 (at 5 dp)."""
    out = {}
    for k, v in markets.items():
        if isinstance(v, dict) and set(v) in _COMPLEMENTS and all(isinstance(x, float) for x in v.values()):
            resid = round(1.0 - sum(v.values()), 5)
            if 0 < abs(resid) <= 1e-4:
                top = max(v, key=v.get)
                v = {**v, top: round(v[top] + resid, 5)}
        out[k] = v
    return out


def predict_upcoming(engine: Engine | None = None, horizon_days: int = HORIZON_DAYS) -> dict:
    engine = engine or get_engine()
    mv_id = model_version_id()
    now = utcnow()
    summary = {"fixtures": 0, "predicted": 0, "revisions": 0, "unchanged": 0, "ineligible": 0, "bets": 0, "no_bet": 0}
    with session_scope() as s:
        ensure_bankroll(s)
        comps = {c.id: c for c in s.scalars(select(Competition))}
        fixtures = s.scalars(select(Fixture).where(
            Fixture.status == "scheduled", Fixture.kickoff_utc > now + timedelta(minutes=10),
            Fixture.kickoff_utc < now + timedelta(days=horizon_days)).order_by(Fixture.kickoff_utc)).all()
        for fx in fixtures:
            summary["fixtures"] += 1
            comp = comps[fx.competition_id]
            snaps = _latest_snapshots(s, fx.id, now)
            ah_line = next((o.ah_line for b, o in snaps.items() if o.ah_line is not None and o.ah_home), None)
            pred = engine.predict(comp.code, fx.home_team_id, fx.away_team_id, fx.neutral,
                                  ah_lines=[ah_line] if ah_line is not None else None)
            if pred is None:
                summary["ineligible"] += 1
                continue
            # ---------------------------------------------------------------- data quality
            ref = next((snaps[b] for b in ("BFE", "PS", "Pinnacle", "Avg") if b in snaps and snaps[b].home), None)
            ref_or = overround([ref.home, ref.draw, ref.away]) if ref and ref.draw else None
            odds_age = min(((now - o.retrieved_at).total_seconds() / 3600 for o in snaps.values()), default=None)
            n_books = len([b for b, o in snaps.items() if b not in ("Max", "Avg") and o.home])
            xg_share, st_share = _stats_shares(s, fx.competition_id, [fx.home_team_id, fx.away_team_id])
            news = s.scalar(select(func.count(TeamNews.id)).where(TeamNews.fixture_id == fx.id))
            q, qb = quality_score(
                now=now, n_home=pred["n_home"], n_away=pred["n_away"],
                last_home=engine.last_played.get(fx.home_team_id), last_away=engine.last_played.get(fx.away_team_id),
                odds={"1X2": any(o.home for o in snaps.values()), "OU25": any(o.over25 for o in snaps.values()),
                      "AH": any(o.ah_home for o in snaps.values()), "n_books": n_books},
                odds_age_h=odds_age, ref_overround=ref_or, book_dispersion=book_dispersion(snaps),
                xg_share=xg_share, stats_share=st_share, name_confidence=_name_confidence(s, fx),
                team_news_available=bool(news))
            n_min = min(pred["n_home"], pred["n_away"])
            conf = confidence_score(q, pred["components"], n_min)
            assessments = assess(pred, snaps, q, conf, n_min, bool(news), odds_age)
            probs = _renormalise(_clean(pred["markets"]))
            # ---------------------------------------------------------------- revision handling
            latest = s.scalars(select(Prediction).where(Prediction.fixture_id == fx.id)
                               .order_by(Prediction.revision.desc())).first()
            inputs = {
                "odds_observation_ids": sorted(o.id for o in snaps.values()),
                "elo": pred["elo"], "n_matches": {"home": pred["n_home"], "away": pred["n_away"]},
                "form": {"home": engine.team_form(fx.home_team_id), "away": engine.team_form(fx.away_team_id),
                         "home_at_home": engine.team_form(fx.home_team_id, 10, "H"),
                         "away_away": engine.team_form(fx.away_team_id, 10, "A")},
                "training_cutoff": engine.ref_date.isoformat(), "team_news_items": news,
                "dc_params": {"rho": engine.dc[comp.code].rho, "home": engine.dc[comp.code].home},
            }
            mk = {a.selection: a.market_prob for a in assessments if a.market == "1X2" and a.market_prob is not None}
            try:
                from .explain import build as build_explanation

                inputs["explanation"] = _clean(build_explanation(
                    engine, comp.code, fx.home_team_id, fx.away_team_id,
                    s.get(Team, fx.home_team_id).name, s.get(Team, fx.away_team_id).name, pred, q, qb, conf,
                    mk if len(mk) == 3 else None, odds_age, xg_share))
            except Exception as exc:  # an explanation failure must never block a prediction
                inputs["explanation"] = {"summary": f"explanation unavailable ({type(exc).__name__})"}
            ihash = _hash({"mv": mv_id, "odds": inputs["odds_observation_ids"],
                           "p": {k: round(v, 3) for k, v in probs["1X2"].items()}})
            reason = ""
            if latest is not None:
                if latest.inputs_hash == ihash:
                    summary["unchanged"] += 1
                    continue
                dp = max(abs(probs["1X2"][k] - latest.probs["1X2"][k]) for k in ("home", "draw", "away"))
                odds_changed = sorted(latest.inputs.get("odds_observation_ids", [])) != inputs["odds_observation_ids"]
                if latest.model_version_id != mv_id:
                    reason = "new model version"
                elif dp >= 0.02:
                    reason = f"model probabilities moved by {dp:.1%} (new results/data)"
                elif odds_changed and _odds_moved(s, latest, snaps):
                    reason = "material odds movement"
                else:
                    summary["unchanged"] += 1
                    continue
            # ---------------------------------------------------------------- bet selection
            already = [(b.market, b.selection) for b in s.scalars(select(VirtualBet).where(VirtualBet.fixture_id == fx.id))]
            slots = settings.risk.max_bets_per_match - len(already)
            chosen = select_bets(assessments, already, slots) if slots > 0 else []
            decision = "BET" if chosen else "NO_BET"
            expl = inputs["explanation"].get("summary", "") + " " + _explain(pred, q, conf, assessments, chosen)
            p = Prediction(fixture_id=fx.id, model_version_id=mv_id, created_at=now, kickoff_utc=fx.kickoff_utc,
                           revision=0 if latest is None else latest.revision + 1,
                           revision_of=None if latest is None else (latest.revision_of or latest.id),
                           revision_reason=reason, probs=probs, component_probs=_clean(pred["components"]),
                           exp_home_goals=round(pred["exp_home_goals"], 3), exp_away_goals=round(pred["exp_away_goals"], 3),
                           confidence=conf, data_quality=q, quality_breakdown=qb, decision=decision, explanation=expl,
                           inputs=_clean(inputs), inputs_hash=ihash,
                           sources=sorted({o.source_url for o in snaps.values()} | {"football-data.co.uk results (model training)"}))
            s.add(p)
            s.flush()
            summary["predicted" if latest is None else "revisions"] += 1
            rows = {}
            for a in assessments:
                va = ValueAssessment(prediction_id=p.id, market=a.market, selection=a.selection, line=a.line,
                                     price=a.price, bookmaker=a.bookmaker, odds_observation_id=a.odds_observation_id,
                                     implied_prob=a.implied_prob, market_prob=a.market_prob, model_prob=a.model_prob,
                                     conservative_prob=a.conservative_prob, overround=a.overround, ev=a.ev,
                                     ev_conservative=a.ev_conservative, qualifies=a in chosen,
                                     reject_reasons=a.reject_reasons, created_at=now)
                s.add(va)
                s.flush()
                rows[id(a)] = va
            for a in chosen:
                if place_bet(s, prediction=p, assessment_row=rows[id(a)], fixture=fx, model_version_id=mv_id):
                    summary["bets"] += 1
            if not chosen:
                summary["no_bet"] += 1
    return summary


def _odds_moved(s, latest: Prediction, snaps: dict) -> bool:
    old = {o.bookmaker: o for o in s.scalars(select(OddsObservation).where(
        OddsObservation.id.in_(latest.inputs.get("odds_observation_ids", []))))}
    for b, o in snaps.items():
        if b in old and o.home and old[b].home:
            a = devig([o.home, o.draw, o.away])
            c = devig([old[b].home, old[b].draw, old[b].away])
            if max(abs(x - y) for x, y in zip(a, c)) >= 0.03:
                return True
    return False


def _explain(pred, q, conf, assessments, chosen) -> str:
    c = pred["components"]
    parts = [
        f"Expected goals {pred['exp_home_goals']:.2f}–{pred['exp_away_goals']:.2f}. "
        f"Dixon-Coles 1X2 {c['dixon_coles']['home']:.0%}/{c['dixon_coles']['draw']:.0%}/{c['dixon_coles']['away']:.0%}, "
        f"Elo {c['elo']['home']:.0%}/{c['elo']['draw']:.0%}/{c['elo']['away']:.0%}. "
        f"Data quality {q:.0f}/100, confidence {conf:.0f}/100."
    ]
    if chosen:
        for a in chosen:
            parts.append(f"VALUE: {a.market} {a.selection}{'' if a.line is None or a.market != 'AH' else f' {a.line:+g}'} @ {a.price:.2f} "
                         f"({a.bookmaker}) — model {a.model_prob:.1%} vs market {a.market_prob:.1%}, "
                         f"EV {a.ev:+.1%}, conservative EV {a.ev_conservative:+.1%}.")
    else:
        parts.append(NO_BET_MSG)
        best = max((a for a in assessments if a.ev_conservative is not None), key=lambda a: a.ev_conservative, default=None)
        if best is not None:
            parts.append(f"Closest candidate: {best.market} {best.selection} (cons. EV {best.ev_conservative:+.1%}); "
                         f"rejected because: {'; '.join(best.reject_reasons) or 'n/a'}.")
    return " ".join(parts)


def evaluate_predictions() -> dict:
    """Score finished fixtures' ORIGINAL predictions (revision 0) — evaluation columns only."""
    n = 0
    with session_scope() as s:
        rows = s.execute(select(Prediction, Fixture).join(Fixture, Fixture.id == Prediction.fixture_id).where(
            Prediction.evaluated.is_(False), Fixture.status == "finished", Fixture.home_goals.is_not(None))).all()
        for p, fx in rows:
            res = "home" if fx.home_goals > fx.away_goals else "draw" if fx.home_goals == fx.away_goals else "away"
            pr = p.probs["1X2"]
            p.eval_brier = round(sum((pr[k] - (1.0 if k == res else 0.0)) ** 2 for k in pr), 5)
            p.eval_logloss = round(-math.log(max(pr[res], 1e-9)), 5)
            p.eval_correct = max(pr, key=pr.get) == res
            p.evaluated = True
            n += 1
    return {"evaluated": n}
