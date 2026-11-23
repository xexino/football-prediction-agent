"""AI Match Analyst — deterministic, evidence-based match reports for Engine B.

Every sentence is generated from numbers that exist in the database or in the model output. Nothing
about injuries, lineups or events is ever asserted unless a data source supplied it. An optional LLM
could later rephrase `sections`, but it may never change the numbers (see docs/AI_INSIGHTS_ENGINE.md).
"""
from __future__ import annotations


def _p(x):
    return f"{x * 100:.0f}%"


def _form_txt(name, f):
    if not f or not f.get("played"):
        return f"{name}: no recent matches in our data."
    return (f"{name}: {f['string']} in the last {f['played']} ({f['w']}W {f['d']}D {f['l']}L), "
            f"scored {f['gf']} / conceded {f['ga']}; BTTS in {f['btts']}, over 2.5 in {f['over25']}, "
            f"{f['clean_sheets']} clean sheets.")


def build_report(*, home: str, away: str, competition: str, markets: dict, features: dict, form: dict,
                 h2h: list, table: dict, engine_a: dict | None, market_1x2: dict | None, unavailable: dict,
                 quality: float, confidence: float, live_available: bool) -> dict:
    x = markets["1X2"]
    eg = markets["EXPECTED_GOALS"]
    fav = max(x, key=x.get)
    fav_name = {"home": home, "away": away, "draw": "a draw"}[fav]
    margin = sorted(x.values())[-1] - sorted(x.values())[-2]
    strength = "clear" if margin > 0.20 else "moderate" if margin > 0.08 else "narrow"
    cs = list(markets["CORRECT_SCORE_TOP"].items())[:3]
    sections = {}
    sections["assessment"] = (
        f"{competition}: Engine B makes {fav_name} the {strength} favourite "
        f"({home} {_p(x['home'])} · draw {_p(x['draw'])} · {away} {_p(x['away'])}). "
        f"Expected goals {eg['home']:.2f}–{eg['away']:.2f} (total {eg['total']:.2f}); most likely scores "
        + ", ".join(f"{k} ({_p(v)})" for k, v in cs) + ".")
    sections["goals"] = (f"Over 2.5 goals {_p(markets['OU25']['over'])}, over 1.5 {_p(markets['OU15']['over'])}, "
                         f"over 3.5 {_p(markets['OU35']['over'])}; both teams to score {_p(markets['BTTS']['yes'])}. "
                         f"Clean sheet {home} {_p(markets['CLEAN_SHEET']['home'])}, {away} {_p(markets['CLEAN_SHEET']['away'])}.")
    if "CORNERS" in markets:
        c = markets["CORNERS"]
        sections["corners_note"] = ("Validation: the corners model is not yet more accurate than the league average "
                                    "(mean abs. error 2.73 vs 2.72 on 4,779 matches) — treat these figures as indicative.")
        sections["corners"] = (f"Expected corners {c['expected']['home']:.1f}–{c['expected']['away']:.1f} "
                               f"(total {c['expected']['total']:.1f}, 80% range {c['interval_80'][0]}–{c['interval_80'][1]}); "
                               f"over 9.5 {_p(c['OU9.5']['over'])}.")
    if "YELLOWS" in markets:
        y = markets["YELLOWS"]
        sections["cards"] = (f"Expected yellow cards {y['expected']['total']:.1f} (over 3.5 {_p(y['OU3.5']['over'])}). "
                             f"Red card in the match: {_p(markets['RED']['any_red_card'])} (league base rate).")
    sections["form"] = " ".join([_form_txt(home, form.get("home")), _form_txt(away, form.get("away"))])

    supporting, contradicting = [], []
    att_h, def_a = features.get("h_goals_att"), features.get("a_goals_def")
    if att_h is not None and def_a is not None:
        txt = f"{home}'s recent scoring rate is {_p(abs(2.718 ** att_h - 1))} {'above' if att_h >= 0 else 'below'} the league average"
        (supporting if (att_h >= 0) == (fav == "home") else contradicting).append(txt)
        txt = f"{away} concede {_p(abs(2.718 ** def_a - 1))} {'more' if def_a >= 0 else 'less'} than average"
        (supporting if (def_a >= 0) == (fav == "home") else contradicting).append(txt)
    elo = features.get("elo_diff")
    if elo is not None:
        gap = elo * 400
        (supporting if (gap > 0) == (fav == "home") else contradicting).append(
            f"rating gap of {gap:+.0f} Elo points including home advantage")
    if table.get("home") and table.get("away"):
        th, ta = table["home"], table["away"]
        better = "home" if th["position"] < ta["position"] else "away"
        (supporting if better == fav else contradicting).append(
            f"league table: {home} #{th['position']} ({th['points']} pts) vs {away} #{ta['position']} ({ta['points']} pts)")
    rh, ra = features.get("rest_home"), features.get("rest_away")
    if rh is not None and ra is not None and abs(rh - ra) >= 3:
        rested = home if rh > ra else away
        (supporting if (rested == home) == (fav == "home") else contradicting).append(
            f"{rested} have had more rest ({rh} vs {ra} days)")
    if h2h:
        hw = sum(1 for m in h2h if m["winner"] == "home_team")
        aw = sum(1 for m in h2h if m["winner"] == "away_team")
        sections["head_to_head"] = (f"Last {len(h2h)} meetings in our data: {home} {hw} wins, {away} {aw} wins, "
                                    f"{len(h2h) - hw - aw} draws (small samples; not a model input).")
    comparison = {}
    if engine_a:
        d = max(abs(engine_a[k] - x[k]) for k in ("home", "draw", "away"))
        comparison["engine_a"] = engine_a
        comparison["engine_a_gap"] = d
        if d >= 0.08:
            contradicting.append(f"Engine A disagrees by up to {_p(d)} on the 1X2 split")
    if market_1x2:
        d = max(abs(market_1x2[k] - x[k]) for k in ("home", "draw", "away"))
        comparison["market"] = market_1x2
        comparison["market_gap"] = d
        if d >= 0.08:
            k = max(("home", "draw", "away"), key=lambda k: abs(market_1x2[k] - x[k]))
            contradicting.append(f"bookmakers price {k} at {_p(market_1x2[k])} vs our {_p(x[k])} — the market may have information we lack")
    missing = ["confirmed lineups, injuries and suspensions (no connected source — not assumed either way)"]
    if not live_available:
        missing.append("live match events/statistics (provider not configured)")
    missing += [f"{k.replace('_', ' ')}: {v}" for k, v in unavailable.items() if k in ("corners", "yellows")]
    if features.get("h_sot_att") is None:
        missing.append("shot statistics for this competition (goal model uses results only)")
    if not market_1x2:
        missing.append("bookmaker odds for comparison")
    level = "low" if confidence < 50 else "moderate" if confidence < 70 else "high"
    sections["confidence"] = (f"Confidence is {level} ({confidence:.0f}/100) with data quality {quality:.0f}/100. "
                              + ("Main uncertainty: " + contradicting[0] + "." if contradicting else ""))
    return {"sections": sections, "supporting": supporting, "contradicting": contradicting, "missing": missing,
            "comparison": comparison, "confidence_level": level,
            "generator": "deterministic templates over model outputs (no LLM configured)"}
