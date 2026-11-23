"""Engine B feature engineering (independent of Engine A).

One chronological pass over all finished matches produces, for every match, the features as they were
known BEFORE kickoff (state is updated only after the row is emitted), so walk-forward training can
never see the future. The same state, advanced to "now", produces features for upcoming fixtures.

Per team (exponentially weighted, alpha = ALPHA): goals, shots on target, corners, yellow cards, fouls,
shots — each "for" and "against", plus venue-specific goals. Per competition: running league means.
Own Elo (different K/home advantage from Engine A). Rest days.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import select

from ..db import Competition, Fixture, MatchStats, session_scope

ALPHA = 0.12            # EWMA weight of the newest match (~8-match memory)
LEAGUE_ALPHA = 0.01
ELO_K, ELO_HOME = 18.0, 55.0
METRICS = ("goals", "sot", "corners", "yellows", "fouls", "shots")
MIN_HISTORY = 6         # matches a team needs before its features are considered informative


def load_history(before: datetime | None = None) -> list[dict]:
    """Finished matches with their football-data.co.uk statistics (None where not provided)."""
    with session_scope() as s:
        comps = {c.id: c.code for c in s.scalars(select(Competition))}
        stats = {r.fixture_id: r for r in s.scalars(select(MatchStats).where(MatchStats.source == "football_data_uk"))}
        q = select(Fixture).where(Fixture.status == "finished", Fixture.home_goals.is_not(None))
        if before is not None:
            q = q.where(Fixture.kickoff_utc < before)
        rows = []
        for f in s.scalars(q.order_by(Fixture.kickoff_utc, Fixture.id)):
            st = stats.get(f.id)
            g = (lambda a: getattr(st, a) if st is not None else None)
            rows.append(dict(id=f.id, comp=comps[f.competition_id], home=f.home_team_id, away=f.away_team_id,
                             kickoff=f.kickoff_utc, neutral=f.neutral,
                             h_goals=f.home_goals, a_goals=f.away_goals,
                             h_sot=g("home_sot"), a_sot=g("away_sot"), h_corners=g("home_corners"), a_corners=g("away_corners"),
                             h_yellows=g("home_yellow"), a_yellows=g("away_yellow"), h_fouls=g("home_fouls"),
                             a_fouls=g("away_fouls"), h_shots=g("home_shots"), a_shots=g("away_shots"),
                             h_red=g("home_red"), a_red=g("away_red"), h_xg=g("home_xg"), a_xg=g("away_xg")))
        return rows


@dataclass
class TeamState:
    n: int = 0
    ew: dict = field(default_factory=dict)        # metric_for / metric_against -> ewma
    n_metric: dict = field(default_factory=lambda: defaultdict(int))
    venue_goals: dict = field(default_factory=dict)  # "H_for", "H_against", "A_for", "A_against"
    last: datetime | None = None
    recent: list = field(default_factory=list)    # (kickoff, gf, ga, venue, comp) last 20


class FeatureState:
    def __init__(self):
        self.teams: dict[int, TeamState] = defaultdict(TeamState)
        self.league: dict[str, dict] = defaultdict(dict)   # comp -> metric_side -> ewma
        self.league_n: dict[str, int] = defaultdict(int)
        self.elo: dict[int, float] = {}
        self.red_rate: dict[str, list] = defaultdict(lambda: [0, 0])  # comp -> [matches with red, matches]

    # ------------------------------------------------------------------ reading
    def _ew(self, team: int, key: str):
        return self.teams[team].ew.get(key)

    def league_mean(self, comp: str, key: str, default: float) -> float:
        return self.league[comp].get(key, default)

    def features(self, comp: str, home: int, away: int, kickoff: datetime, neutral: bool = False) -> dict:
        """Pre-match feature snapshot for a fixture (nothing about the match itself is used)."""
        th, ta = self.teams[home], self.teams[away]
        f = {"comp": comp, "n_home": th.n, "n_away": ta.n}
        defaults = {"goals": 1.3, "sot": 4.3, "corners": 5.0, "yellows": 1.9, "fouls": 11.5, "shots": 12.0}
        for m in METRICS:
            for side, (atk, dfn) in (("h", (home, away)), ("a", (away, home))):
                lg = self.league_mean(comp, f"{m}_{'H' if side == 'h' else 'A'}", defaults[m])
                lg_all = self.league_mean(comp, f"{m}_all", defaults[m])
                a_for = self._ew(atk, f"{m}_for")
                d_against = self._ew(dfn, f"{m}_against")
                f[f"{side}_{m}_league"] = lg
                f[f"{side}_{m}_att"] = math.log(max(a_for, 0.05) / lg_all) if a_for is not None else None
                f[f"{side}_{m}_def"] = math.log(max(d_against, 0.05) / lg_all) if d_against is not None else None
        hv, av = th.venue_goals, ta.venue_goals
        f["h_home_gf"] = hv.get("H_for")
        f["a_away_gf"] = av.get("A_for")
        eh, ea = self.elo.get(home, 1500.0), self.elo.get(away, 1500.0)
        f["elo_home"], f["elo_away"] = eh, ea
        f["elo_diff"] = (eh - ea + (0 if neutral else ELO_HOME)) / 400
        f["rest_home"] = min((kickoff - th.last).days, 21) if th.last else None
        f["rest_away"] = min((kickoff - ta.last).days, 21) if ta.last else None
        rr = self.red_rate[comp]
        f["league_red_rate"] = (rr[0] + 1) / (rr[1] + 10)
        f["league_matches"] = self.league_n[comp]
        return f

    # ------------------------------------------------------------------ updating (after the match)
    def update(self, m: dict) -> None:
        comp, h, a = m["comp"], m["home"], m["away"]
        for metric in METRICS:
            hv, av = m.get(f"h_{metric}"), m.get(f"a_{metric}")
            if hv is None or av is None:
                continue
            for team, f_, a_ in ((h, hv, av), (a, av, hv)):
                st = self.teams[team]
                for key, val in ((f"{metric}_for", f_), (f"{metric}_against", a_)):
                    old = st.ew.get(key)
                    st.ew[key] = val if old is None else (1 - ALPHA) * old + ALPHA * val
                st.n_metric[metric] += 1
            lg = self.league[comp]
            for key, val in ((f"{metric}_H", hv), (f"{metric}_A", av), (f"{metric}_all", (hv + av) / 2)):
                old = lg.get(key)
                lg[key] = val if old is None else (1 - LEAGUE_ALPHA) * old + LEAGUE_ALPHA * val
        for team, venue, gf, ga in ((h, "H", m["h_goals"], m["a_goals"]), (a, "A", m["a_goals"], m["h_goals"])):
            st = self.teams[team]
            for key, val in ((f"{venue}_for", gf), (f"{venue}_against", ga)):
                old = st.venue_goals.get(key)
                st.venue_goals[key] = val if old is None else (1 - 2 * ALPHA) * old + 2 * ALPHA * val
            st.n += 1
            st.last = m["kickoff"]
            st.recent = (st.recent + [(m["kickoff"], gf, ga, venue, comp)])[-20:]
        if m.get("h_red") is not None and m.get("a_red") is not None:
            rr = self.red_rate[comp]
            rr[0] += int((m["h_red"] or 0) + (m["a_red"] or 0) > 0)
            rr[1] += 1
        self.league_n[comp] += 1
        # Elo with goal-difference multiplier
        eh, ea = self.elo.get(h, 1500.0), self.elo.get(a, 1500.0)
        exp = 1 / (1 + 10 ** (-(eh - ea + (0 if m.get("neutral") else ELO_HOME)) / 400))
        res = 1.0 if m["h_goals"] > m["a_goals"] else 0.5 if m["h_goals"] == m["a_goals"] else 0.0
        gd = abs(m["h_goals"] - m["a_goals"])
        k = ELO_K * (1 if gd <= 1 else 1.5 if gd == 2 else 1.75)
        self.elo[h], self.elo[a] = eh + k * (res - exp), ea - k * (res - exp)

    def form(self, team: int, n: int = 10) -> dict:
        r = self.teams[team].recent[-n:]
        if not r:
            return {"played": 0}
        w = sum(1 for x in r if x[1] > x[2])
        d = sum(1 for x in r if x[1] == x[2])
        return {"played": len(r), "w": w, "d": d, "l": len(r) - w - d, "gf": sum(x[1] for x in r), "ga": sum(x[2] for x in r),
                "btts": sum(1 for x in r if x[1] > 0 and x[2] > 0), "over25": sum(1 for x in r if x[1] + x[2] > 2),
                "clean_sheets": sum(1 for x in r if x[2] == 0), "failed_to_score": sum(1 for x in r if x[1] == 0),
                "string": "".join("W" if x[1] > x[2] else "D" if x[1] == x[2] else "L" for x in r)}


def build_rows(history: list[dict]) -> tuple[list[dict], FeatureState]:
    """Return (rows with pre-match features + targets, final state)."""
    st = FeatureState()
    rows = []
    for m in history:
        f = st.features(m["comp"], m["home"], m["away"], m["kickoff"], m.get("neutral", False))
        f.update(id=m["id"], kickoff=m["kickoff"], home=m["home"], away=m["away"])
        for metric in METRICS:
            f[f"y_h_{metric}"], f[f"y_a_{metric}"] = m.get(f"h_{metric}"), m.get(f"a_{metric}")
        f["y_red"] = None if m.get("h_red") is None else int((m["h_red"] or 0) + (m["a_red"] or 0) > 0)
        rows.append(f)
        st.update(m)
    return rows, st


def design(row: dict, metric: str, side: str) -> np.ndarray | None:
    """Feature vector for one count target. Returns None when the core inputs are missing."""
    opp = "a" if side == "h" else "h"
    att, dfn = row.get(f"{side}_{metric}_att"), row.get(f"{opp}_{metric}_def")
    if att is None or dfn is None:
        return None
    elo = row["elo_diff"] if side == "h" else -row["elo_diff"]
    rest = row.get(f"rest_{'home' if side == 'h' else 'away'}")
    vec = [att, dfn, elo, math.log(max(row[f"{side}_{metric}_league"], 0.05)),
           0.0 if rest is None else min(rest, 14) / 7 - 1]
    if metric == "goals":  # shots on target carry extra information about future scoring
        sa, sd = row.get(f"{side}_sot_att"), row.get(f"{opp}_sot_def")
        vec += [sa if sa is not None else 0.0, sd if sd is not None else 0.0, float(sa is not None and sd is not None)]
    return np.array(vec, float)


FEATURE_NAMES = {
    "goals": ["attack_ewma", "opp_defence_ewma", "elo_diff", "log_league_mean", "rest_days", "sot_attack", "opp_sot_defence", "has_sot"],
    "default": ["attack_ewma", "opp_defence_ewma", "elo_diff", "log_league_mean", "rest_days"],
}
