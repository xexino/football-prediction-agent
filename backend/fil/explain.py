"""Plain-language explanations built ONLY from quantities the models actually used.

Factors are Dixon-Coles parameters (home advantage, attack/defence ratings), the Elo gap, and the
data-quality components. Recent form is shown as context and explicitly labelled as not a model input.
"""
from __future__ import annotations

import math


def _pct(logv: float) -> str:
    return f"{(math.exp(logv) - 1) * 100:+.0f}%"


def build(engine, comp: str, home_id: int, away_id: int, home: str, away: str, pred: dict, quality: float,
          qb: dict, confidence: float, market_1x2: dict | None, odds_age_h: float | None, xg_share: float) -> dict:
    p = engine.dc[comp]
    hs = engine.team_strength(comp, home_id)
    as_ = engine.team_strength(comp, away_id)
    factors = []
    if hs and as_:
        factors += [
            {"factor": "Home advantage", "effect": _pct(p.home), "on": f"{home} goals", "value": round(p.home, 3),
             "text": f"league home advantage raises {home}'s expected goals by {_pct(p.home)}"},
            {"factor": f"{home} attack rating", "effect": _pct(hs[0]), "on": f"{home} goals", "value": round(hs[0], 3),
             "text": f"{home} score {_pct(hs[0])} vs a league-average attack"},
            {"factor": f"{away} defence rating", "effect": _pct(as_[1]), "on": f"{home} goals", "value": round(as_[1], 3),
             "text": f"{away} concede {_pct(as_[1])} vs a league-average defence"},
            {"factor": f"{away} attack rating", "effect": _pct(as_[0]), "on": f"{away} goals", "value": round(as_[0], 3),
             "text": f"{away} score {_pct(as_[0])} vs a league-average attack"},
            {"factor": f"{home} defence rating", "effect": _pct(hs[1]), "on": f"{away} goals", "value": round(hs[1], 3),
             "text": f"{home} concede {_pct(hs[1])} vs a league-average defence"},
        ]
    eh, ea = pred["elo"]["home"], pred["elo"]["away"]
    if eh is not None and ea is not None:
        gap = eh - ea + engine.elo.home_adv
        factors.append({"factor": "Elo rating gap (incl. home)", "effect": f"{gap:+.0f} pts", "on": "1X2",
                        "value": round(gap, 1), "text": f"Elo gap of {gap:+.0f} points including home advantage"})
    main = sorted([f for f in factors if f["factor"] != "Elo rating gap (incl. home)"],
                  key=lambda f: -abs(f["value"]))[:3]

    weakening, missing = [], []
    if qb.get("team_news", 0) == 0:
        missing.append("team news, injuries, suspensions and lineups (no connected source) — NOT treated as a signal either way")
    if xg_share == 0:
        missing.append("xG and shot statistics for this competition")
    if qb.get("odds_markets", 0) < 9:
        missing.append("odds for some markets (O/U 2.5 and/or Asian handicap)")
    n_min = min(pred["n_home"], pred["n_away"])
    if n_min < 20:
        weakening.append(f"small sample: only {n_min} recent matches for one team in this competition")
    dcp, elo = pred["components"]["dixon_coles"], pred["components"]["elo"]
    dis = max(abs(dcp[k] - elo[k]) for k in ("home", "draw", "away"))
    model_dis = None
    if dis >= 0.06:
        model_dis = f"Dixon-Coles and Elo disagree by up to {dis:.0%} on the 1X2 split"
        weakening.append(model_dis)
    market_dis = None
    if market_1x2:
        ens = pred["components"]["ensemble"]
        gap = max(abs(ens[k] - market_1x2[k]) for k in ("home", "draw", "away"))
        if gap >= 0.06:
            k = max(("home", "draw", "away"), key=lambda k: abs(ens[k] - market_1x2[k]))
            market_dis = f"model differs from the de-vigged market by {ens[k] - market_1x2[k]:+.0%} on {k}"
            weakening.append(market_dis + " (the market may know something the model does not)")
    else:
        missing.append("a sharp market reference price")
    freshness = None if odds_age_h is None else f"odds snapshot is {odds_age_h:.0f}h old"
    if odds_age_h is not None and odds_age_h > 48:
        weakening.append(freshness)
    level = "low" if confidence < 50 else "moderate" if confidence < 70 else "high"
    ens = pred["components"]["ensemble"]
    fav = max(ens, key=ens.get)
    who = {"home": home, "away": away, "draw": "the draw"}[fav]
    summary = (f"Most likely outcome: {who} ({ens[fav]:.0%}); expected goals {pred['exp_home_goals']:.2f}–{pred['exp_away_goals']:.2f}. "
               f"Main drivers: {'; '.join(f['text'] for f in main) or 'n/a'}. "
               f"Confidence is {level} ({confidence:.0f}/100)"
               + (f" because {weakening[0]}" if weakening else "") + ".")
    return {"summary": summary, "main_factors": main, "all_factors": factors, "weakening": weakening, "missing": missing,
            "model_disagreement": model_dis, "market_disagreement": market_dis, "freshness": freshness,
            "confidence_level": level,
            "note": "Factors are fitted model parameters; recent form is context only and not a direct model input."}
