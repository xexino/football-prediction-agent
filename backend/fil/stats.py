"""Performance analytics computed from the immutable ledger."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import numpy as np
from sqlalchemy import select

from .config import settings
from .db import BankrollTransaction, Competition, Fixture, ModelVersion, Prediction, VirtualBet, session_scope
from .timeutil import iso


def _group(bets, key):
    g = defaultdict(list)
    for b in bets:
        g[key(b)].append(b)
    return {k: perf(v) for k, v in sorted(g.items())}


def perf(bets) -> dict:
    settled = [b for b in bets if b["status"] != "pending"]
    staked = sum(b["stake"] for b in settled)
    returns = sum(b["payout"] or 0 for b in settled)
    wins = sum(1 for b in settled if b["status"] in ("won", "half_won"))
    losses = sum(1 for b in settled if b["status"] in ("lost", "half_lost"))
    clv = [b["clv"] for b in settled if b.get("clv") is not None]
    return {"bets": len(bets), "settled": len(settled), "pending": len(bets) - len(settled), "won": wins, "lost": losses,
            "void": sum(1 for b in settled if b["status"] == "void"), "staked": round(staked, 2),
            "returns": round(returns, 2), "profit": round(returns - staked, 2),
            "roi": round((returns - staked) / staked, 4) if staked else None,
            "win_rate": round(wins / (wins + losses), 4) if (wins + losses) else None,
            "avg_odds": round(float(np.mean([b["price"] for b in bets])), 3) if bets else None,
            "avg_clv": round(float(np.mean(clv)), 4) if clv else None}


def odds_bucket(p: float) -> str:
    for lo, hi in ((1.5, 2.0), (2.0, 2.5), (2.5, 3.5), (3.5, 5.01)):
        if lo <= p < hi:
            return f"{lo:.1f}-{min(hi, 5.0):.1f}"
    return "other"


def bets_table(s, since: datetime | None = None) -> list[dict]:
    comps = {c.id: c for c in s.scalars(select(Competition))}
    models = {m.id: f"{m.name} {m.version}" for m in s.scalars(select(ModelVersion))}
    q = select(VirtualBet, Fixture).join(Fixture, Fixture.id == VirtualBet.fixture_id)
    if since:
        q = q.where(VirtualBet.created_at >= since)
    out = []
    for b, f in s.execute(q.order_by(VirtualBet.created_at)).all():
        out.append({"id": b.id, "fixture_id": f.id, "competition": comps[f.competition_id].code, "market": b.market,
                    "selection": b.selection, "line": b.line, "price": b.price, "stake": b.stake,
                    "status": b.status, "payout": b.payout, "profit": b.profit, "clv": b.clv,
                    "created_at": b.created_at, "settled_at": b.settled_at, "model": models.get(b.model_version_id)})
    return out


def summary() -> dict:
    with session_scope() as s:
        bets = bets_table(s)
        txs = s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.id)).all()
        start = round(sum(t.amount for t in txs if t.tx_type in ("initial", "top_up")), 2) if txs else settings.risk.initial_bankroll
        bal = txs[-1].balance_after if txs else start
        # bankroll history excluding pending stakes (equity = balance + pending stakes at cost)
        hist, pending_stakes = [], 0.0
        for t in txs:
            if t.tx_type == "stake":
                pending_stakes += -t.amount
            elif t.tx_type in ("payout", "refund"):
                pass
            hist.append({"t": iso(t.created_at), "balance": t.balance_after, "type": t.tx_type})
        settled = sorted((b for b in bets if b["status"] != "pending"), key=lambda b: b["settled_at"])
        cum, peak, dd, curve = 0.0, 0.0, 0.0, []
        for b in settled:
            cum += (b["payout"] or 0) - b["stake"]
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
            curve.append({"t": iso(b["settled_at"]), "cum_profit": round(cum, 2), "bankroll": round(start + cum, 2)})
        p = perf(bets)
        rows = s.execute(select(Prediction, Fixture).join(Fixture, Fixture.id == Prediction.fixture_id).where(
            Prediction.evaluated.is_(True), Prediction.revision == 0)).all()
        preds = [p for p, _ in rows]
        cal = calibration_from_predictions([(p.probs["1X2"], "home" if f.home_goals > f.away_goals else
                                             "draw" if f.home_goals == f.away_goals else "away") for p, f in rows])
        return {
            "starting_bankroll": start, "current_bankroll": round(bal, 2),
            "pending_exposure": round(sum(b["stake"] for b in bets if b["status"] == "pending"), 2),
            "equity": round(bal + sum(b["stake"] for b in bets if b["status"] == "pending"), 2),
            **p, "max_drawdown": round(dd, 2), "bankroll_history": hist, "pnl_curve": curve,
            "by_competition": _group(bets, lambda b: b["competition"]),
            "by_market": _group(bets, lambda b: b["market"]),
            "by_odds_range": _group(bets, lambda b: odds_bucket(b["price"])),
            "by_model": _group(bets, lambda b: b["model"] or "?"),
            "prediction_metrics": {
                "evaluated": len(preds),
                "brier": round(float(np.mean([x.eval_brier for x in preds])), 4) if preds else None,
                "log_loss": round(float(np.mean([x.eval_logloss for x in preds])), 4) if preds else None,
                "accuracy": round(float(np.mean([x.eval_correct for x in preds])), 4) if preds else None,
                "calibration": cal,
            },
        }


def calibration_from_predictions(pairs, bins=5):
    """pairs: [(probs_1x2_dict, actual_outcome_key)]"""
    pts = [(v, 1.0 if k == res else 0.0) for probs, res in pairs for k, v in probs.items()]
    if not pts:
        return []
    edges = np.linspace(0, 1, bins + 1)
    arr = np.array(pts)
    out = []
    for i in range(bins):
        m = (arr[:, 0] >= edges[i]) & ((arr[:, 0] < edges[i + 1]) if i < bins - 1 else (arr[:, 0] <= 1))
        if m.sum():
            out.append({"bin": f"{edges[i]:.1f}-{edges[i + 1]:.1f}", "predicted": round(float(arr[m, 0].mean()), 4),
                        "observed": round(float(arr[m, 1].mean()), 4), "n": int(m.sum())})
    return out
