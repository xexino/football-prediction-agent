"""Walk-forward (time-aware) validation of the models and of the value-betting rules.

At each step date t the models are trained ONLY on matches before t, then used to predict the
matches in [t, t+step). Pre-match bookmaker prices (published before kickoff) are used for the
simulated strategy; closing prices are used only for closing-line value (CLV) afterwards.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select

from .config import settings
from .db import BacktestRun, Competition, Fixture, ModelVersion, OddsObservation, session_scope
from .models.engine import MODEL_NAME, MODEL_VERSION, PARAMS, Engine, load_matches
from .models.markets import devig, settle
from .value import plausible
from .quality import confidence as confidence_score
from .quality import score as quality_score
from .value import assess, book_dispersion, select_bets
from .timeutil import utcnow

DEFAULT_COMPS = ["ENG1", "ESP1", "ITA1", "GER1", "FRA1", "POR1", "NED1", "BEL1", "TUR1", "SCO1", "ENG2"]


def _metrics(rows):
    if not rows:
        return None
    ll = [-math.log(max(p[o], 1e-9)) for p, o in rows]
    br = [sum((p[k] - (1.0 if k == o else 0.0)) ** 2 for k in range(3)) for p, o in rows]
    acc = [int(np.argmax(p) == o) for p, o in rows]
    return {"n": len(rows), "log_loss": round(float(np.mean(ll)), 4), "brier": round(float(np.mean(br)), 4),
            "accuracy": round(float(np.mean(acc)), 4)}


def _calibration(rows, bins=10):
    edges = np.linspace(0, 1, bins + 1)
    out = []
    probs = np.array([p[k] for p, o in rows for k in range(3)])
    hits = np.array([1.0 if o == k else 0.0 for p, o in rows for k in range(3)])
    for i in range(bins):
        m = (probs >= edges[i]) & (probs < edges[i + 1] if i < bins - 1 else probs <= 1)
        if m.sum() >= 10:
            out.append({"bin": f"{edges[i]:.1f}-{edges[i + 1]:.1f}", "predicted": round(float(probs[m].mean()), 4),
                        "observed": round(float(hits[m].mean()), 4), "n": int(m.sum())})
    return out


def _ece(rows, bins=10):
    """Expected calibration error over all 1X2 outcome probabilities."""
    probs = np.array([p[k] for p, o in rows for k in range(3)])
    hits = np.array([1.0 if o == k else 0.0 for p, o in rows for k in range(3)])
    if not len(probs):
        return None
    idx = np.minimum((probs * bins).astype(int), bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(probs[m].mean() - hits[m].mean())
    return round(float(ece), 4)


def _bootstrap_roi(profits, n=2000, seed=11):
    """95% bootstrap interval of ROI per unit staked (flat 1u stakes)."""
    if len(profits) < 10:
        return None
    rng = np.random.default_rng(seed)
    arr = np.array(profits)
    sims = rng.choice(arr, size=(n, len(arr)), replace=True).mean(axis=1)
    lo, hi = np.percentile(sims, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def _drawdown(pnl):
    peak, dd, cum = 0.0, 0.0, 0.0
    for x in pnl:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return round(dd, 2)


def _season(d):
    return f"{d.year}/{(d.year + 1) % 100:02d}" if d.month >= 7 else f"{d.year - 1}/{d.year % 100:02d}"


def _by_prob_range(rows):
    """Reliability of the ensemble's favourite probability, bucketed."""
    out = {}
    for lo, hi in ((0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
        sel = [(p, o) for p, o in rows if lo <= max(p) < hi]
        if sel:
            out[f"{lo:.1f}-{min(hi, 1):.1f}"] = {"n": len(sel), "mean_prob": round(float(np.mean([max(p) for p, _ in sel])), 4),
                                               "hit_rate": round(float(np.mean([int(np.argmax(p) == o) for p, o in sel])), 4)}
    return out


def run_backtest(start: datetime | None = None, end: datetime | None = None, step_days: int = 14,
                 comps: list[str] | None = None, progress=None, params: dict | None = None,
                 per_match: list | None = None, store: bool = True) -> dict:
    """params: Engine parameter overrides (experiments). per_match: if a list is given, (fixture_id, kickoff,
    ensemble 1X2, market 1X2 or None, outcome) is appended for paired comparisons. store=False: no BacktestRun row."""
    comps = comps or DEFAULT_COMPS
    end = end or utcnow()
    start = start or datetime(end.year - 1 if end.month >= 8 else end.year - 2, 8, 1)
    all_matches = load_matches(before=end)
    with session_scope() as s:
        comp_ids = {c.code: c.id for c in s.scalars(select(Competition))}
    target = [m for m in all_matches if m["comp"] in comps and start <= m["kickoff"] < end]
    ids = [m["id"] for m in target]
    odds = defaultdict(dict)
    closing = defaultdict(dict)
    with session_scope() as s:
        for chunk in range(0, len(ids), 900):
            for o in s.scalars(select(OddsObservation).where(OddsObservation.fixture_id.in_(ids[chunk:chunk + 900]))):
                (odds if o.kind == "pre_match" else closing)[o.fixture_id][o.bookmaker] = o
    # baseline: historical outcome frequencies per competition (from data before `start`)
    freq = defaultdict(lambda: np.array([1.0, 1.0, 1.0]))
    for m in all_matches:
        if m["kickoff"] < start and m["comp"] in comps:
            freq[m["comp"]][0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2] += 1

    res = defaultdict(list)
    by_comp = defaultdict(lambda: defaultdict(list))
    bets = []
    weights_grid = defaultdict(list)
    blend_rows = []
    dates = []
    prev = None
    t = start
    steps = 0
    while t < end:
        t2 = min(t + timedelta(days=step_days), end)
        window = [m for m in target if t <= m["kickoff"] < t2]
        if window:
            eng = Engine(params={**PARAMS, **(params or {})}).build(all_matches, t, comps=comps, prev=prev)
            prev = eng
            for m in window:
                snaps = odds.get(m["id"], {})
                ah = next((o.ah_line for o in snaps.values() if o.ah_line is not None and o.ah_home), None)
                pr = eng.predict(m["comp"], m["home_id"], m["away_id"], m["neutral"], ah_lines=[ah] if ah is not None else None)
                if pr is None:
                    continue
                o = 0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2
                comp_p = pr["components"]
                vec = lambda d: [d["home"], d["draw"], d["away"]]
                rows = {"ensemble": vec(comp_p["ensemble"]), "dixon_coles": vec(comp_p["dixon_coles"]),
                        "elo": vec(comp_p["elo"]), "baseline": list(freq[m["comp"]] / freq[m["comp"]].sum())}
                # clean reference: implausible (corrupt) exchange rows are skipped, see value.plausible
                ref = next((snaps[b] for b in ("BFE", "PS", "Avg") if b in snaps and plausible(b, snaps[b], ("home", "draw", "away"))), None)
                if ref is not None:
                    rows["market"] = devig([ref.home, ref.draw, ref.away])
                if per_match is not None:
                    per_match.append((m["id"], m["kickoff"], rows["ensemble"], rows.get("market"), o))
                dates.append(m["kickoff"])
                for k, v in rows.items():
                    res[k].append((v, o))
                    by_comp[m["comp"]][k].append((v, o))
                for w in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
                    pv = [w * a + (1 - w) * b for a, b in zip(rows["dixon_coles"], rows["elo"])]
                    weights_grid[w].append((pv, o))
                if "market" in rows:
                    blend_rows.append((m["kickoff"], rows["ensemble"], rows["market"], o))
                # ---------------- value strategy with the live rules
                if not snaps:
                    continue
                n_min = min(pr["n_home"], pr["n_away"])
                q, _ = quality_score(now=m["kickoff"], n_home=pr["n_home"], n_away=pr["n_away"],
                                     last_home=eng.last_played.get(m["home_id"]), last_away=eng.last_played.get(m["away_id"]),
                                     odds={"1X2": True, "OU25": any(x.over25 for x in snaps.values()),
                                           "AH": any(x.ah_home for x in snaps.values()), "n_books": len(snaps) - 2},
                                     odds_age_h=36, ref_overround=None if ref is None else sum(1 / x for x in (ref.home, ref.draw, ref.away)) - 1,
                                     book_dispersion=book_dispersion(snaps), xg_share=1.0 if m.get("hxg") is not None else 0.0,
                                     stats_share=1.0, name_confidence=1.0, team_news_available=False)
                conf = confidence_score(q, comp_p, n_min)
                ass = assess(pr, snaps, q, conf, n_min, False, 36)
                for a in select_bets(ass, [], settings.risk.max_bets_per_match):
                    outcome, payout, _ = settle(a.market, a.selection, a.line, a.price, 1.0, m["hg"], m["ag"])
                    cl = closing.get(m["id"], {}).get(a.bookmaker)
                    cp = None
                    if cl is not None:
                        cp = {"1X2": getattr(cl, a.selection, None) if a.market == "1X2" else None,
                              "OU25": getattr(cl, f"{a.selection}25", None) if a.market == "OU25" else None,
                              "AH": (cl.ah_home if a.selection == "home" else cl.ah_away) if a.market == "AH" and cl.ah_line == a.line else None}[a.market]
                    bets.append({"date": m["kickoff"].isoformat(), "comp": m["comp"], "market": a.market, "selection": a.selection,
                                 "price": a.price, "ev_c": a.ev_conservative, "outcome": outcome, "profit": round(payout - 1.0, 3),
                                 "clv": round(a.price / cp - 1, 4) if cp else None})
        steps += 1
        if progress:
            progress(steps, t)
        t = t2

    def strat(bs):
        if not bs:
            return {"bets": 0}
        pnl = [b["profit"] for b in bs]
        clv = [b["clv"] for b in bs if b["clv"] is not None]
        return {"bets": len(bs), "profit": round(sum(pnl), 2), "roi": round(sum(pnl) / len(bs), 4),
                "roi_95ci": _bootstrap_roi(pnl),
                "win_rate": round(sum(1 for b in bs if b["profit"] > 0) / len(bs), 4),
                "max_drawdown": _drawdown(pnl), "avg_clv": round(float(np.mean(clv)), 4) if clv else None,
                "avg_price": round(float(np.mean([b["price"] for b in bs])), 3)}

    # model-vs-market blend: fitted on the first half of the period, checked on the second half
    blend = {}
    if len(blend_rows) > 200:
        blend_rows.sort(key=lambda r: r[0])
        half = len(blend_rows) // 2
        for name, part in (("first_half", blend_rows[:half]), ("second_half", blend_rows[half:])):
            blend[name] = {f"{w:.2f}": _metrics([([w * a + (1 - w) * b for a, b in zip(e, mk)], o) for _, e, mk, o in part])["log_loss"]
                           for w in np.linspace(0, 1, 11)}
        blend["optimal_w_first_half"] = float(min(blend["first_half"], key=blend["first_half"].get))
        # power calibration p_k^t / sum: fitted on the first half, judged on the second half only
        from .models.calibration import apply_power, fit_power

        first = [(e, o) for _, e, _, o in blend_rows[:half]]
        second = [(e, o) for _, e, _, o in blend_rows[half:]]
        t = fit_power(first)
        cal2 = [(apply_power(e, t), o) for e, o in second]
        blend_cal = {"power_t_fitted_on_first_half": round(t, 4),
                     "second_half_raw": _metrics(second) | {"ece": _ece(second)},
                     "second_half_calibrated": _metrics(cal2) | {"ece": _ece(cal2)}}
        blend_cal["improves_out_of_sample"] = blend_cal["second_half_calibrated"]["log_loss"] < blend_cal["second_half_raw"]["log_loss"]
        blend["calibration_check"] = blend_cal
        blend["note"] = "w = weight on the model in w*model + (1-w)*market; 0 means the market already contains all model information."
    odds_ranges = [(1.5, 2.0), (2.0, 3.0), (3.0, 5.01)]
    out = {
        "model": f"{MODEL_NAME} {MODEL_VERSION}", "start": start.isoformat(), "end": end.isoformat(),
        "step_days": step_days, "competitions": comps,
        "metrics": {k: (_metrics(v) or {}) | {"ece": _ece(v)} for k, v in res.items()},
        "by_probability_range": _by_prob_range(res["ensemble"]),
        "by_season": {season: _metrics([r for r, d in zip(res["ensemble"], dates) if _season(d) == season])
                      for season in sorted({_season(d) for d in dates})},
        "by_competition": {c: {k: _metrics(v) for k, v in d.items()} for c, d in by_comp.items()},
        "calibration": {"ensemble": _calibration(res["ensemble"]), "market": _calibration(res.get("market", []))},
        "ensemble_weight_scan": {str(w): _metrics(v)["log_loss"] for w, v in weights_grid.items() if v},
        "market_blend_scan": blend,
        "value_rules": {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(settings.value).items()},
        "strategy": strat(bets),
        "strategy_by_market": {mk: strat([b for b in bets if b["market"] == mk]) for mk in ("1X2", "OU25", "AH")},
        "strategy_by_competition": {c: strat([b for b in bets if b["comp"] == c]) for c in comps},
        "strategy_by_odds": {f"{a:.1f}-{b:.1f}": strat([x for x in bets if a <= x["price"] < b]) for a, b in odds_ranges},
        "cumulative_pnl": [round(x, 2) for x in np.cumsum([b["profit"] for b in sorted(bets, key=lambda b: b["date"])])][::max(1, len(bets) // 200)],
        "note": "Walk-forward: models refit every step on data strictly before the step date. Strategy uses Bet365 "
                "pre-match prices with the live value rules. Small samples are not evidence of profitability.",
    }
    out["reference_prices"] = "clean: exchange rows above 8 % overround skipped (value.plausible)"
    if not store:
        return out
    with session_scope() as s:
        s.add(BacktestRun(params={"start": out["start"], "end": out["end"], "step_days": step_days, "comps": comps}, results=out))
        mv = s.scalars(select(ModelVersion).where(ModelVersion.name == MODEL_NAME, ModelVersion.version == MODEL_VERSION)).first()
        if mv is not None:
            mv.metrics = {"backtest": out["metrics"], "strategy": out["strategy"], "evaluated_at": utcnow().isoformat()}
    return out
