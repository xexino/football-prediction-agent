"""Prediction engine: trains Dixon-Coles (per competition) + Elo/ordered-logit and combines them.

Everything is strictly time-aware: `build(ref_date)` only uses matches that kicked off before
`ref_date`, so the same code serves live predictions and walk-forward backtests.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select

from ..db import Competition, Fixture, MatchStats, session_scope
from . import dixon_coles as dc
from .elo import Elo, OrderedLogit
from .markets import markets_from_matrix, rescale_to_1x2

MODEL_NAME = "fil-ensemble"
MODEL_VERSION = "1.0.0"
PARAMS = {
    "dc_xi_per_day": 0.0019, "dc_ridge": 2.0, "dc_window_days": 1100, "dc_xg_weight": 0.5,
    "elo_k": 20, "elo_home_adv": 65, "w_dc": 0.6, "w_elo": 0.4, "min_comp_matches": 300,
    "description": "Ensemble of time-weighted Dixon-Coles (goals blended with xG where available) and "
                   "goal-difference Elo mapped through an ordered logit. Derived markets come from the DC score "
                   "matrix rescaled to the ensemble 1X2.",
}


def load_matches(before: datetime | None = None) -> list[dict]:
    with session_scope() as s:
        comps = {c.id: c.code for c in s.scalars(select(Competition))}
        q = select(Fixture).where(Fixture.status == "finished", Fixture.home_goals.is_not(None))
        if before is not None:
            q = q.where(Fixture.kickoff_utc < before)
        fixtures = s.scalars(q.order_by(Fixture.kickoff_utc)).all()
        xg = {fid: (hx, ax) for fid, hx, ax in s.execute(
            select(MatchStats.fixture_id, MatchStats.home_xg, MatchStats.away_xg).where(MatchStats.home_xg.is_not(None)))}
        return [dict(id=f.id, comp=comps[f.competition_id], home_id=f.home_team_id, away_id=f.away_team_id,
                     hg=f.home_goals, ag=f.away_goals, kickoff=f.kickoff_utc, neutral=f.neutral,
                     hxg=xg.get(f.id, (None, None))[0], axg=xg.get(f.id, (None, None))[1]) for f in fixtures]


@dataclass
class Engine:
    params: dict = field(default_factory=lambda: dict(PARAMS))
    ref_date: datetime | None = None
    elo: Elo = field(default_factory=Elo)
    ologit: OrderedLogit = field(default_factory=OrderedLogit)
    dc: dict = field(default_factory=dict)  # comp -> DCParams
    comp_counts: dict = field(default_factory=dict)
    last_played: dict = field(default_factory=dict)
    form: dict = field(default_factory=lambda: defaultdict(list))  # team -> [(kickoff, gf, ga, venue, comp)]

    # ------------------------------------------------------------------ training
    def build(self, matches: list[dict], ref_date: datetime, comps: list[str] | None = None, prev: "Engine" | None = None):
        self.ref_date = ref_date
        self.elo = Elo(k=self.params["elo_k"], home_adv=self.params["elo_home_adv"])
        xs, ys = [], []
        by_comp = defaultdict(list)
        window_start = ref_date - timedelta(days=self.params["dc_window_days"])
        for m in matches:
            if m["kickoff"] >= ref_date:
                break
            # Elo: record pre-match diff for ordered-logit training, then update
            if m["comp"][-1].isdigit() or m["comp"].startswith(("U", "CAF")):
                x = self.elo.diff(m["home_id"], m["away_id"], m["neutral"]) / 400
                if self.elo.games.get(m["home_id"], 0) >= 10 and self.elo.games.get(m["away_id"], 0) >= 10:
                    xs.append(x)
                    ys.append(0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2)
            self.elo.update(m["home_id"], m["away_id"], m["hg"], m["ag"], m["comp"], m["neutral"])
            if m["kickoff"] >= window_start:
                by_comp[m["comp"]].append(m)
            self.last_played[m["home_id"]] = m["kickoff"]
            self.last_played[m["away_id"]] = m["kickoff"]
            self.form[m["home_id"]].append((m["kickoff"], m["hg"], m["ag"], "H", m["comp"]))
            self.form[m["away_id"]].append((m["kickoff"], m["ag"], m["hg"], "A", m["comp"]))
        if len(xs) > 500:
            # ordered logit on the most recent 20k club matches
            self.ologit = OrderedLogit().fit(xs[-20000:], ys[-20000:])
        for comp, ms in by_comp.items():
            self.comp_counts[comp] = len(ms)
            if comps is not None and comp not in comps:
                continue
            if len(ms) < self.params["min_comp_matches"] or not comp[-1].isdigit():
                continue
            init = prev.dc.get(comp) if prev else None
            self.dc[comp] = dc.fit_competition(ms, ref_date, xi=self.params["dc_xi_per_day"],
                                               ridge=self.params["dc_ridge"], init=init)
        return self

    # ------------------------------------------------------------------ prediction
    def team_matches_in_comp(self, comp: str, team: int) -> int:
        p = self.dc.get(comp)
        return p.n_matches.get(team, 0) if p else 0

    def predict(self, comp: str, home: int, away: int, neutral: bool = False, ah_lines=None) -> dict | None:
        p = self.dc.get(comp)
        if p is None:
            return None
        rates = p.rates(home, away, neutral)
        if rates is None:
            return None
        lam, mu = rates
        m = dc.score_matrix(lam, mu, p.rho)
        dc_1x2 = markets_from_matrix(m)["1X2"]
        x = self.elo.diff(home, away, neutral) / 400
        elo_1x2 = dict(zip(("home", "draw", "away"), map(float, self.ologit.probs([x])[0])))
        w_dc, w_elo = self.params["w_dc"], self.params["w_elo"]
        ens = {k: w_dc * dc_1x2[k] + w_elo * elo_1x2[k] for k in ("home", "draw", "away")}
        tot = sum(ens.values())
        ens = {k: v / tot for k, v in ens.items()}
        m2 = rescale_to_1x2(m, (ens["home"], ens["draw"], ens["away"]))
        markets = markets_from_matrix(m2, ah_lines=ah_lines)
        return {
            "markets": markets, "matrix": m2, "exp_home_goals": lam, "exp_away_goals": mu,
            "components": {"dixon_coles": dc_1x2, "elo": elo_1x2, "ensemble": ens},
            "elo": {"home": self.elo.ratings.get(home), "away": self.elo.ratings.get(away)},
            "n_home": p.n_matches.get(home, 0), "n_away": p.n_matches.get(away, 0),
        }

    def team_strength(self, comp: str, team: int) -> tuple[float, float] | None:
        """(attack, defence) log-rate parameters of the fitted Dixon-Coles model (0 = league average)."""
        p = self.dc.get(comp)
        if p is None or team not in p.teams:
            return None
        i = p.teams.index(team)
        return float(p.att[i]), float(p.dfn[i])

    def team_form(self, team: int, n: int = 10, venue: str | None = None) -> dict:
        rows = [r for r in self.form.get(team, []) if venue is None or r[3] == venue][-n:]
        if not rows:
            return {"played": 0}
        gf = [r[1] for r in rows]
        ga = [r[2] for r in rows]
        w = sum(1 for a, b in zip(gf, ga) if a > b)
        d = sum(1 for a, b in zip(gf, ga) if a == b)
        return {
            "played": len(rows), "w": w, "d": d, "l": len(rows) - w - d,
            "gf_avg": round(float(np.mean(gf)), 2), "ga_avg": round(float(np.mean(ga)), 2),
            "clean_sheets": sum(1 for x in ga if x == 0), "failed_to_score": sum(1 for x in gf if x == 0),
            "string": "".join("W" if a > b else "D" if a == b else "L" for a, b in zip(gf, ga)),
            "last_match": rows[-1][0].isoformat(),
        }
