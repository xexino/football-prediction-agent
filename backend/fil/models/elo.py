"""Goal-difference-weighted Elo ratings + ordered-logit mapping to 1X2 probabilities."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


def tier_of(comp_code: str) -> int:
    d = comp_code[-1]
    return int(d) if d.isdigit() else 1


@dataclass
class Elo:
    k: float = 20.0
    home_adv: float = 65.0
    init: float = 1500.0
    ratings: dict = field(default_factory=dict)
    games: dict = field(default_factory=dict)
    team_comp: dict = field(default_factory=dict)  # team -> last competition code

    def _enter(self, team, comp: str):
        """Handle a team appearing in a (new) competition: promoted/relegated teams are re-seeded
        relative to their new league instead of carrying a rating from a different pool."""
        prev = self.team_comp.get(team)
        if prev == comp:
            return
        peers = [self.ratings[t] for t, c in self.team_comp.items() if c == comp and t != team]
        if team not in self.ratings:
            self.ratings[team] = float(np.percentile(peers, 25)) if len(peers) >= 6 else self.init
        elif prev is not None and len(peers) >= 6 and tier_of(prev) != tier_of(comp) and not comp.startswith("U"):
            q = 20 if tier_of(comp) < tier_of(prev) else 80  # promoted -> weak, relegated -> strong
            self.ratings[team] = float(np.percentile(peers, q))
        if not comp.startswith(("UCL", "UEL", "UECL", "CAF")):
            self.team_comp[team] = comp

    def expected(self, home, away, neutral=False) -> float:
        rh, ra = self.ratings.get(home, self.init), self.ratings.get(away, self.init)
        d = rh - ra + (0 if neutral else self.home_adv)
        return 1 / (1 + 10 ** (-d / 400))

    def diff(self, home, away, neutral=False) -> float:
        return self.ratings.get(home, self.init) - self.ratings.get(away, self.init) + (0 if neutral else self.home_adv)

    def update(self, home, away, hg, ag, comp: str, neutral=False):
        self._enter(home, comp)
        self._enter(away, comp)
        e = self.expected(home, away, neutral)
        s = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        gd = abs(hg - ag)
        mult = 1.0 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        delta = self.k * mult * (s - e)
        self.ratings[home] = self.ratings.get(home, self.init) + delta
        self.ratings[away] = self.ratings.get(away, self.init) - delta
        self.games[home] = self.games.get(home, 0) + 1
        self.games[away] = self.games.get(away, 0) + 1


@dataclass
class OrderedLogit:
    """P(away) = σ(θ1 − βx), P(away or draw) = σ(θ2 − βx); x = Elo diff / 400."""

    beta: float = 2.0
    th1: float = -0.6
    th2: float = 0.6

    def probs(self, x):
        x = np.asarray(x, float)
        c1 = expit(self.th1 - self.beta * x)
        c2 = expit(self.th2 - self.beta * x)
        pa, pd, ph = c1, c2 - c1, 1 - c2
        return np.stack([ph, pd, pa], axis=-1)

    def fit(self, x, outcome):
        """outcome: 0 home, 1 draw, 2 away."""
        x = np.asarray(x, float)
        y = np.asarray(outcome)

        def nll(p):
            b, t1, gap = p
            m = OrderedLogit(b, t1, t1 + abs(gap) + 1e-6)
            pr = np.clip(m.probs(x), 1e-9, 1)
            return -np.sum(np.log(pr[np.arange(len(y)), y]))

        res = minimize(nll, [self.beta, self.th1, self.th2 - self.th1], method="Nelder-Mead",
                       options={"maxiter": 2000, "xatol": 1e-4, "fatol": 1e-4})
        b, t1, gap = res.x
        self.beta, self.th1, self.th2 = float(b), float(t1), float(t1 + abs(gap))
        return self
