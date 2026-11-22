"""Time-weighted Dixon-Coles bivariate Poisson model (Dixon & Coles, 1997).

log λ_home = c + h + att[home] + def[away]
log λ_away = c + att[away] + def[home]
with the Dixon-Coles low-score correction τ(ρ), exponential time decay ξ, and a ridge
prior on team parameters (shrinks small samples toward a prior mean; newly-arrived teams
get a slightly weaker prior). Optional xG blending replaces observed goals in the Poisson
term by w·goals + (1−w)·xG where xG is available.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10


@dataclass
class DCParams:
    teams: list
    att: np.ndarray
    dfn: np.ndarray
    c: float
    home: float
    rho: float
    n_matches: dict
    converged: bool

    def rates(self, home_id, away_id, neutral: bool = False):
        idx = {t: i for i, t in enumerate(self.teams)}
        if home_id not in idx or away_id not in idx:
            return None
        i, j = idx[home_id], idx[away_id]
        h = 0.0 if neutral else self.home
        lam = np.exp(self.c + h + self.att[i] + self.dfn[j])
        mu = np.exp(self.c + self.att[j] + self.dfn[i])
        return float(lam), float(mu)


def tau_matrix(lam: float, mu: float, rho: float, n: int = MAX_GOALS + 1) -> np.ndarray:
    t = np.ones((n, n))
    t[0, 0] = 1 - lam * mu * rho
    t[0, 1] = 1 + lam * rho
    t[1, 0] = 1 + mu * rho
    t[1, 1] = 1 - rho
    return t


def score_matrix(lam: float, mu: float, rho: float = 0.0, n: int = MAX_GOALS + 1) -> np.ndarray:
    """P(home=i, away=j) for i, j in 0..n-1, normalised to sum to 1."""
    ph = poisson.pmf(np.arange(n), lam)
    pa = poisson.pmf(np.arange(n), mu)
    m = np.outer(ph, pa) * tau_matrix(lam, mu, rho, n)
    m = np.clip(m, 0, None)
    return m / m.sum()


def fit(home_idx, away_idx, hg, ag, days_ago, n_teams, xi=0.0019, ridge=2.0, prior_mean=None,
        hxg=None, axg=None, xg_weight=0.5, init=None):
    """Fit by maximum weighted likelihood with analytic gradient (L-BFGS-B)."""
    home_idx = np.asarray(home_idx)
    away_idx = np.asarray(away_idx)
    hg = np.asarray(hg, float)
    ag = np.asarray(ag, float)
    w = np.exp(-xi * np.asarray(days_ago, float))
    xh, xa = hg.copy(), ag.copy()
    if hxg is not None:
        hxg = np.asarray(hxg, float)
        axg = np.asarray(axg, float)
        ok = ~np.isnan(hxg) & ~np.isnan(axg)
        xh[ok] = xg_weight * hg[ok] + (1 - xg_weight) * hxg[ok]
        xa[ok] = xg_weight * ag[ok] + (1 - xg_weight) * axg[ok]
    pm_att = np.zeros(n_teams) if prior_mean is None else prior_mean[0]
    pm_def = np.zeros(n_teams) if prior_mean is None else prior_mean[1]
    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)
    T = n_teams

    def unpack(p):
        return p[:T], p[T:2 * T], p[2 * T], p[2 * T + 1], p[2 * T + 2]

    def negll(p):
        att, dfn, c, h, rho = unpack(p)
        ll_ = c + h + att[home_idx] + dfn[away_idx]
        lm_ = c + att[away_idx] + dfn[home_idx]
        lam, mu = np.exp(ll_), np.exp(lm_)
        tau = np.ones_like(lam)
        tau[m00] = 1 - lam[m00] * mu[m00] * rho
        tau[m01] = 1 + lam[m01] * rho
        tau[m10] = 1 + mu[m10] * rho
        tau[m11] = 1 - rho
        if np.any(tau <= 0):
            return 1e12, np.zeros_like(p)
        ll = w * (np.log(tau) + xh * ll_ - lam + xa * lm_ - mu)
        pen = ridge * (np.sum((att - pm_att) ** 2) + np.sum((dfn - pm_def) ** 2))
        # gradients
        g_l = w * (xh - lam)
        g_m = w * (xa - mu)
        dl = np.zeros_like(lam)
        dm = np.zeros_like(lam)
        dr = np.zeros_like(lam)
        dl[m00] = -lam[m00] * mu[m00] * rho / tau[m00]
        dm[m00] = dl[m00]
        dr[m00] = -lam[m00] * mu[m00] / tau[m00]
        dl[m01] = lam[m01] * rho / tau[m01]
        dr[m01] = lam[m01] / tau[m01]
        dm[m10] = mu[m10] * rho / tau[m10]
        dr[m10] = mu[m10] / tau[m10]
        dr[m11] = -1 / tau[m11]
        g_l = g_l + w * dl
        g_m = g_m + w * dm
        g_att = np.bincount(home_idx, g_l, T) + np.bincount(away_idx, g_m, T)
        g_def = np.bincount(away_idx, g_l, T) + np.bincount(home_idx, g_m, T)
        g_att -= 2 * ridge * (att - pm_att)
        g_def -= 2 * ridge * (dfn - pm_def)
        grad = np.concatenate([g_att, g_def, [g_l.sum() + g_m.sum(), g_l.sum(), np.sum(w * dr)]])
        return -(ll.sum() - pen), -grad

    p0 = init if init is not None else np.concatenate([pm_att, pm_def, [0.25, 0.25, -0.05]])
    bounds = [(-3, 3)] * (2 * T) + [(-2, 2), (-0.5, 1.0), (-0.3, 0.3)]
    res = minimize(negll, p0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
    return res.x, bool(res.success)


def fit_competition(matches, ref_date, xi=0.0019, ridge=2.0, use_xg=True, newcomer_threshold=8, init=None):
    """matches: list of dicts with home_id, away_id, hg, ag, kickoff (datetime), hxg, axg."""
    teams = sorted({m["home_id"] for m in matches} | {m["away_id"] for m in matches})
    idx = {t: i for i, t in enumerate(teams)}
    hi = np.array([idx[m["home_id"]] for m in matches])
    ai = np.array([idx[m["away_id"]] for m in matches])
    hg = np.array([m["hg"] for m in matches], float)
    ag = np.array([m["ag"] for m in matches], float)
    days = np.array([(ref_date - m["kickoff"]).total_seconds() / 86400 for m in matches])
    n_matches = {t: 0 for t in teams}
    recent = {t: 0 for t in teams}
    for m, d in zip(matches, days):
        n_matches[m["home_id"]] += 1
        n_matches[m["away_id"]] += 1
        if d < 400:
            recent[m["home_id"]] += 1
            recent[m["away_id"]] += 1
    # teams with little recent history in this competition (e.g. promoted) get a weaker prior
    pm_att = np.array([-0.15 if recent[t] < newcomer_threshold else 0.0 for t in teams])
    pm_def = np.array([0.15 if recent[t] < newcomer_threshold else 0.0 for t in teams])
    hxg = axg = None
    if use_xg:
        hxg = np.array([np.nan if m.get("hxg") is None else m["hxg"] for m in matches], float)
        axg = np.array([np.nan if m.get("axg") is None else m["axg"] for m in matches], float)
        if np.all(np.isnan(hxg)):
            hxg = axg = None
    p0 = None
    if init is not None and init.teams == teams:
        p0 = np.concatenate([init.att, init.dfn, [init.c, init.home, init.rho]])
    x, ok = fit(hi, ai, hg, ag, days, len(teams), xi=xi, ridge=ridge, prior_mean=(pm_att, pm_def),
                hxg=hxg, axg=axg, init=p0)
    T = len(teams)
    return DCParams(teams=teams, att=x[:T], dfn=x[T:2 * T], c=float(x[2 * T]), home=float(x[2 * T + 1]),
                    rho=float(x[2 * T + 2]), n_matches=n_matches, converged=ok)
