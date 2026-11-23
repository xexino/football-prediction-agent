"""Walk-forward validation of Engine B against Engine A, simple baselines and the betting market.

At each step date t both engines are refit on matches strictly before t and predict [t, t+step).
Features are pre-match by construction; closing odds are used only for CLV, never as inputs.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from scipy.stats import poisson
from sqlalchemy import select

from ..backtest import DEFAULT_COMPS, _bootstrap_roi, _calibration, _drawdown, _ece
from ..db import EBModelVersion, EBValidationRun, OddsObservation, session_scope
from ..models.engine import Engine, load_matches
from ..models.markets import devig, settle
from ..timeutil import utcnow
from . import betting
from .features import build_rows, load_history
from .model import MODEL_NAME, MODEL_VERSION, EngineBModel, score_matrix


def _ll(p, o):
    return -math.log(max(p[o], 1e-9))


def _m(rows):
    if not rows:
        return None
    return {"n": len(rows), "log_loss": round(float(np.mean([_ll(p, o) for p, o in rows])), 4),
            "brier": round(float(np.mean([sum((p[k] - (k == o)) ** 2 for k in range(3)) for p, o in rows])), 4),
            "accuracy": round(float(np.mean([int(np.argmax(p) == o) for p, o in rows])), 4), "ece": _ece(rows)}


def _bin(rows):
    if not rows:
        return None
    return {"n": len(rows), "log_loss": round(float(np.mean([-math.log(max(p if y else 1 - p, 1e-9)) for p, y in rows])), 4),
            "brier": round(float(np.mean([(p - y) ** 2 for p, y in rows])), 4)}


def run(start: datetime | None = None, end: datetime | None = None, step_days: int = 14, comps=None, with_engine_a=True,
        progress=None) -> dict:
    comps = comps or DEFAULT_COMPS
    end = end or utcnow()
    start = start or datetime(end.year - 1 if end.month >= 8 else end.year - 2, 8, 1)
    hist = load_history(before=end)
    rows, _ = build_rows(hist)
    a_matches = load_matches(before=end) if with_engine_a else []
    target = [r for r in rows if r["comp"] in comps and start <= r["kickoff"] < end]
    ids = [r["id"] for r in target]
    odds, closing = defaultdict(dict), defaultdict(dict)
    with session_scope() as s:
        for i in range(0, len(ids), 900):
            for o in s.scalars(select(OddsObservation).where(OddsObservation.fixture_id.in_(ids[i:i + 900]))):
                (odds if o.kind == "pre_match" else closing)[o.fixture_id][o.bookmaker] = o
    freq = defaultdict(lambda: np.ones(3))
    for r in rows:
        if r["kickoff"] < start and r["comp"] in comps:
            freq[r["comp"]][0 if r["y_h_goals"] > r["y_a_goals"] else 1 if r["y_h_goals"] == r["y_a_goals"] else 2] += 1
    res = defaultdict(list)
    by_comp = defaultdict(lambda: defaultdict(list))
    ou25, btts = defaultdict(list), defaultdict(list)
    counts = defaultdict(lambda: defaultdict(list))
    bets = []
    t, prev_a, steps = start, None, 0
    comp_of = {r["id"]: r["comp"] for r in target}
    while t < end:
        t2 = min(t + timedelta(days=step_days), end)
        window = [r for r in target if t <= r["kickoff"] < t2]
        if window:
            mb = EngineBModel().fit(rows, t)
            ea = Engine().build(a_matches, t, comps=comps, prev=prev_a) if with_engine_a else None
            prev_a = ea
            for r in window:
                pb = mb.predict(r)
                if not pb["markets"]:
                    continue
                o = 0 if r["y_h_goals"] > r["y_a_goals"] else 1 if r["y_h_goals"] == r["y_a_goals"] else 2
                x = pb["markets"]["1X2"]
                rec = {"engine_b": [x["home"], x["draw"], x["away"]], "naive": list(freq[r["comp"]] / freq[r["comp"]].sum())}
                # simple Poisson baseline: league home/away means only
                lh, la = r["h_goals_league"], r["a_goals_league"]
                sm = score_matrix(lh, la, 0.0)
                i_, j_ = np.indices(sm.shape)
                rec["simple_poisson"] = [float(sm[i_ > j_].sum()), float(sm[i_ == j_].sum()), float(sm[i_ < j_].sum())]
                pa = ea.predict(r["comp"], r["home"], r["away"]) if ea else None
                if pa is not None:
                    c = pa["components"]["ensemble"]
                    rec["engine_a"] = [c["home"], c["draw"], c["away"]]
                snaps = odds.get(r["id"], {})
                ref = next((snaps[b] for b in ("BFE", "PS", "Avg") if b in snaps and snaps[b].home and snaps[b].draw), None)
                if ref is not None:
                    rec["market"] = devig([ref.home, ref.draw, ref.away])
                if "engine_a" not in rec and with_engine_a:
                    continue  # compare on identical matches only
                for k, v in rec.items():
                    res[k].append((v, o))
                    by_comp[r["comp"]][k].append((v, o))
                tot = r["y_h_goals"] + r["y_a_goals"]
                ou25["engine_b"].append((pb["markets"]["OU25"]["over"], int(tot > 2.5)))
                btts["engine_b"].append((pb["markets"]["BTTS"]["yes"], int(r["y_h_goals"] > 0 and r["y_a_goals"] > 0)))
                if pa is not None:
                    ou25["engine_a"].append((pa["markets"]["OU25"]["over"], int(tot > 2.5)))
                    btts["engine_a"].append((pa["markets"]["BTTS"]["yes"], int(r["y_h_goals"] > 0 and r["y_a_goals"] > 0)))
                ouref = next((snaps[b] for b in ("BFE", "PS", "Avg") if b in snaps and snaps[b].over25 and snaps[b].under25), None)
                if ouref is not None:
                    ou25["market"].append((devig([ouref.over25, ouref.under25])[0], int(tot > 2.5)))
                for metric, lines in (("corners", (9.5,)), ("yellows", (3.5,))):
                    mk = pb["markets"].get(metric.upper())
                    yh, ya = r.get(f"y_h_{metric}"), r.get(f"y_a_{metric}")
                    if mk is None or yh is None:
                        continue
                    actual = yh + ya
                    lgmean = r[f"h_{metric}_league"] + r[f"a_{metric}_league"]
                    counts[metric]["abs_err"].append(abs(mk["expected"]["total"] - actual))
                    counts[metric]["baseline_abs_err"].append(abs(lgmean - actual))
                    counts[metric]["in_80"].append(int(mk["interval_80"][0] <= actual <= mk["interval_80"][1]))
                    for ln in lines:
                        p = mk[f"OU{ln}"]["over"]
                        counts[metric][f"ll_ou{ln}"].append(-math.log(max(p if actual > ln else 1 - p, 1e-9)))
                        base_p = 1 - poisson.cdf(int(ln), lgmean)
                        counts[metric][f"baseline_ll_ou{ln}"].append(-math.log(max(base_p if actual > ln else 1 - base_p, 1e-9)))
                # Engine B strategy with its own live risk rules
                if snaps:
                    from ..quality import _lin  # noqa: F401  (keeps import graph explicit)
                    cands = betting.candidates(pb["markets"], snaps, quality=80.0, confidence=70.0)
                    for c in betting.choose(cands, 0):
                        outcome, payout, _ = settle(c["market"], c["selection"], c["line"], c["price"], 1.0,
                                                    r["y_h_goals"], r["y_a_goals"])
                        cl = closing.get(r["id"], {}).get(c["bookmaker"])
                        cp = None
                        if cl is not None:
                            cp = getattr(cl, c["selection"], None) if c["market"] == "1X2" else getattr(cl, f"{c['selection']}25", None)
                        bets.append({"date": r["kickoff"].isoformat(), "comp": r["comp"], "market": c["market"],
                                     "price": c["price"], "profit": round(payout - 1, 3), "clv": round(c["price"] / cp - 1, 4) if cp else None})
        steps += 1
        if progress:
            progress(steps, t)
        t = t2

    def strat(bs):
        if not bs:
            return {"bets": 0}
        pnl = [b["profit"] for b in bs]
        clv = [b["clv"] for b in bs if b["clv"] is not None]
        return {"bets": len(bs), "profit": round(sum(pnl), 2), "roi": round(sum(pnl) / len(bs), 4), "roi_95ci": _bootstrap_roi(pnl),
                "win_rate": round(sum(1 for p in pnl if p > 0) / len(bs), 4), "max_drawdown": _drawdown(pnl),
                "avg_clv": round(float(np.mean(clv)), 4) if clv else None}

    out = {
        "model": f"{MODEL_NAME} {MODEL_VERSION}", "start": start.isoformat(), "end": end.isoformat(), "step_days": step_days,
        "competitions": comps, "note": "Walk-forward; both engines refit every step on data strictly before the step date; "
                                       "metrics computed on identical matches.",
        "metrics_1x2": {k: _m(v) for k, v in res.items()},
        "by_competition": {c: {k: _m(v) for k, v in d.items()} for c, d in by_comp.items()},
        "calibration": {"engine_b": _calibration(res["engine_b"]), "engine_a": _calibration(res.get("engine_a", []))},
        "ou25": {k: _bin(v) for k, v in ou25.items()}, "btts": {k: _bin(v) for k, v in btts.items()},
        "counts": {m: {k: round(float(np.mean(v)), 4) for k, v in d.items()} | {"n": len(d["abs_err"])} for m, d in counts.items()},
        "strategy_engine_b": strat(bets),
        "strategy_engine_b_by_market": {mk: strat([b for b in bets if b["market"] == mk]) for mk in ("1X2", "OU25")},
        "risk_rules": {k: (list(v) if isinstance(v, tuple) else v) for k, v in betting.RISK.__dict__.items()},
    }
    with session_scope() as s:
        s.add(EBValidationRun(model=out["model"], params={"start": out["start"], "end": out["end"], "step": step_days,
                                                          "comps": comps}, results=out))
        mv = s.scalars(select(EBModelVersion).where(EBModelVersion.name == MODEL_NAME, EBModelVersion.version == MODEL_VERSION)).first()
        if mv is not None:
            mv.metrics = {"validation": out["metrics_1x2"], "ou25": out["ou25"], "btts": out["btts"], "counts": out["counts"],
                          "strategy": out["strategy_engine_b"], "at": utcnow().isoformat()}
    return out
