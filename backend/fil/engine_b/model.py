"""Engine B models: feature-based Poisson GLMs per count market.

* goals    : home/away Poisson GLMs -> score matrix with a fitted Dixon-Coles low-score correction (rho)
* corners, yellows, shots, sot, fouls: home/away Poisson GLMs; totals use a negative-binomial dispersion
  estimated on the training set (counts like corners are over-dispersed)
* red cards: league base rate only (too rare for team-level modelling) — labelled as such
Everything is fitted only on rows that kicked off before the training cutoff.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from scipy.stats import nbinom, poisson
from sklearn.linear_model import PoissonRegressor

from .features import FEATURE_NAMES, MIN_HISTORY, design

MODEL_NAME = "eb-insights"
MODEL_VERSION = "1.0.0"
COUNT_METRICS = ("goals", "corners", "yellows", "sot", "shots", "fouls")
WINDOW_DAYS = 1100
MAXG = 10
LINES = {"corners": (7.5, 8.5, 9.5, 10.5), "yellows": (2.5, 3.5, 4.5), "sot": (7.5, 8.5, 9.5), "shots": (22.5, 24.5, 26.5),
         "fouls": (20.5, 22.5, 24.5)}
TEAM_LINES = {"corners": (3.5, 4.5, 5.5), "yellows": (0.5, 1.5, 2.5)}


@dataclass
class EngineBModel:
    cutoff: datetime | None = None
    glm: dict = field(default_factory=dict)        # (metric, side) -> PoissonRegressor
    dispersion: dict = field(default_factory=dict)  # metric -> k (None = Poisson)
    rho: float = 0.0
    n_train: dict = field(default_factory=dict)
    params: dict = field(default_factory=lambda: {"alpha": 1e-3, "window_days": WINDOW_DAYS, "min_history": MIN_HISTORY})

    # ------------------------------------------------------------------ training
    def fit(self, rows: list[dict], cutoff: datetime, metrics=COUNT_METRICS) -> "EngineBModel":
        self.cutoff = cutoff
        start = cutoff - timedelta(days=WINDOW_DAYS)
        train = [r for r in rows if start <= r["kickoff"] < cutoff and r["n_home"] >= MIN_HISTORY and r["n_away"] >= MIN_HISTORY]
        for metric in metrics:
            preds_tot, y_tot = [], []
            fitted = {}
            for side in ("h", "a"):
                X, y = [], []
                for r in train:
                    t = r.get(f"y_{side}_{metric}")
                    v = design(r, metric, side)
                    if t is None or v is None:
                        continue
                    X.append(v)
                    y.append(t)
                if len(y) < 400:
                    break
                m = PoissonRegressor(alpha=self.params["alpha"], max_iter=300)
                m.fit(np.array(X), np.array(y, float))
                fitted[side] = m
            if len(fitted) < 2:
                continue
            self.glm[(metric, "h")], self.glm[(metric, "a")] = fitted["h"], fitted["a"]
            # dispersion of totals
            for r in train[-6000:]:
                vh, va = design(r, metric, "h"), design(r, metric, "a")
                th, ta = r.get(f"y_h_{metric}"), r.get(f"y_a_{metric}")
                if vh is None or va is None or th is None or ta is None:
                    continue
                preds_tot.append(float(fitted["h"].predict(vh[None])[0] + fitted["a"].predict(va[None])[0]))
                y_tot.append(th + ta)
            mu, y = np.array(preds_tot), np.array(y_tot, float)
            self.n_train[metric] = int(len(y))
            excess = np.mean((y - mu) ** 2) - np.mean(mu)
            self.dispersion[metric] = float(np.mean(mu ** 2) / excess) if excess > 0.05 else None
            if metric == "goals":
                self.rho = _fit_rho(train, fitted)
        return self

    def ready(self, metric: str) -> bool:
        return (metric, "h") in self.glm

    # ------------------------------------------------------------------ prediction
    def expectations(self, row: dict, metric: str) -> tuple[float, float] | None:
        if not self.ready(metric):
            return None
        vh, va = design(row, metric, "h"), design(row, metric, "a")
        if vh is None or va is None:
            return None
        return float(self.glm[(metric, "h")].predict(vh[None])[0]), float(self.glm[(metric, "a")].predict(va[None])[0])

    def predict(self, row: dict) -> dict:
        out, unavailable = {}, {}
        enough = row["n_home"] >= MIN_HISTORY and row["n_away"] >= MIN_HISTORY
        g = self.expectations(row, "goals") if enough else None
        if g is None:
            return {"markets": {}, "matrix": None, "unavailable": {"all": "insufficient team history or model not trained"}}
        lh, la = g
        mat = score_matrix(lh, la, self.rho)
        out.update(goal_markets(mat, lh, la))
        for metric in ("corners", "yellows", "sot", "shots", "fouls"):
            e = self.expectations(row, metric)
            if e is None:
                unavailable[metric] = ("no historical statistics for this competition/teams" if self.ready(metric)
                                       else "model not trained (insufficient data)")
                continue
            out[metric.upper()] = count_markets(e[0], e[1], self.dispersion.get(metric), metric)
        out["RED"] = {"any_red_card": round(row["league_red_rate"], 4),
                      "note": "league base rate (team-level red-card modelling is not statistically defensible)"}
        for m in ("player_shots", "player_goals", "assists", "offsides", "goal_timing", "possession"):
            unavailable[m] = "no reliable data source connected (needs API-Football or a paid provider)"
        return {"markets": out, "matrix": mat, "unavailable": unavailable}


def _fit_rho(train, fitted) -> float:
    """Dixon-Coles low-score correction fitted by maximum likelihood on the training rows."""
    lam, mu, hg, ag = [], [], [], []
    for r in train[-8000:]:
        vh, va = design(r, "goals", "h"), design(r, "goals", "a")
        if vh is None or va is None or r.get("y_h_goals") is None:
            continue
        lam.append(fitted["h"].predict(vh[None])[0])
        mu.append(fitted["a"].predict(va[None])[0])
        hg.append(r["y_h_goals"])
        ag.append(r["y_a_goals"])
    lam, mu, hg, ag = map(np.array, (lam, mu, hg, ag))
    best, best_ll = 0.0, -1e18
    for rho in np.linspace(-0.2, 0.15, 36):
        tau = np.ones_like(lam)
        tau = np.where((hg == 0) & (ag == 0), 1 - lam * mu * rho, tau)
        tau = np.where((hg == 0) & (ag == 1), 1 + lam * rho, tau)
        tau = np.where((hg == 1) & (ag == 0), 1 + mu * rho, tau)
        tau = np.where((hg == 1) & (ag == 1), 1 - rho, tau)
        if np.any(tau <= 0):
            continue
        ll = np.sum(np.log(tau))
        if ll > best_ll:
            best, best_ll = float(rho), ll
    return best


def score_matrix(lh: float, la: float, rho: float = 0.0) -> np.ndarray:
    n = MAXG
    m = np.outer(poisson.pmf(np.arange(n), lh), poisson.pmf(np.arange(n), la))
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def goal_markets(m: np.ndarray, lh: float, la: float) -> dict:
    n = m.shape[0]
    i, j = np.indices((n, n))
    tot = i + j
    ph, pd, pa = float(m[i > j].sum()), float(m[i == j].sum()), float(m[i < j].sum())
    p_goal = 1 - float(m[0, 0])
    share = lh / (lh + la) if lh + la > 0 else 0.5
    flat = sorted(((float(m[a, b]), f"{a}-{b}") for a in range(n) for b in range(n)), reverse=True)
    res = {
        "1X2": {"home": ph, "draw": pd, "away": pa},
        "DC": {"1X": ph + pd, "12": ph + pa, "X2": pd + pa},
        "BTTS": {"yes": float(m[(i > 0) & (j > 0)].sum()), "no": float(m[(i == 0) | (j == 0)].sum())},
        "CLEAN_SHEET": {"home": float(m[:, 0].sum()), "away": float(m[0, :].sum())},
        "FIRST_TO_SCORE": {"home": p_goal * share, "away": p_goal * (1 - share), "none": float(m[0, 0]),
                           "note": "assumes goals follow independent Poisson processes (no in-match dynamics)"},
        "EXPECTED_GOALS": {"home": lh, "away": la, "total": lh + la},
        "CORRECT_SCORE_TOP": {k: p for p, k in flat[:8]},
    }
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        res[f"OU{str(line).replace('.', '')}"] = {"over": float(m[tot > line].sum()), "under": float(m[tot < line].sum())}
    return res


def _dist(mu: float, k: float | None, upto: int) -> np.ndarray:
    x = np.arange(upto + 1)
    if k is None or k > 500:
        return poisson.pmf(x, mu)
    return nbinom.pmf(x, k, k / (k + mu))


def count_markets(mh: float, ma: float, k: float | None, metric: str) -> dict:
    tot = mh + ma
    upto = int(max(60, tot * 4))
    d = _dist(tot, k, upto)
    cdf = np.cumsum(d)
    res = {"expected": {"home": mh, "away": ma, "total": tot}, "dispersion_k": k,
           "interval_80": [int(np.searchsorted(cdf, 0.1)), int(np.searchsorted(cdf, 0.9))]}
    for line in LINES.get(metric, ()):
        over = float(1 - cdf[int(math.floor(line))])
        res[f"OU{line}"] = {"over": over, "under": 1 - over}
    for line in TEAM_LINES.get(metric, ()):
        for side, mu in (("home", mh), ("away", ma)):
            c = np.cumsum(poisson.pmf(np.arange(int(line) + 1), mu))
            res[f"{side}_OU{line}"] = {"over": float(1 - c[int(math.floor(line))])}
    if metric == "corners":
        res["home_distribution"] = [round(float(p), 4) for p in poisson.pmf(np.arange(13), mh)]
        res["away_distribution"] = [round(float(p), 4) for p in poisson.pmf(np.arange(13), ma)]
    return res
