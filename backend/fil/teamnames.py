"""Team-name normalisation and cross-provider resolution."""
from __future__ import annotations

import difflib
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Team, TeamAlias

_STOP = {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "sv", "fk", "sk", "cd", "ud", "rc", "club", "de", "the", "calcio", "1."}
_SUBS = {
    "manchester": "man", "united": "utd", "utd": "utd", "city": "city", "saint": "st", "st.": "st",
    "wolverhampton wanderers": "wolves", "nottingham": "nottm", "internazionale": "inter", "borussia": "",
    "munchen": "munich", "monchengladbach": "mgladbach", "olympique": "", "sporting": "sp",
}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().strip()
    s = s.replace("&", " and ").replace("-", " ").replace("'", "")
    for a, b in _SUBS.items():
        if " " in a:
            s = s.replace(a, b)
    toks = [_SUBS.get(t, t) for t in re.split(r"[\s\.]+", s)]
    toks = [t for t in toks if t and t not in _STOP]
    return " ".join(toks)


class TeamResolver:
    """Resolve provider team names to internal team ids.

    The first provider to introduce a team defines its canonical name. Other providers are
    matched via exact alias, then normalised alias, then fuzzy matching restricted to the
    candidate set (e.g. teams already playing in the same competition). Low-confidence
    matches are recorded with their confidence so the data-quality score can penalise them.
    """

    def __init__(self, session: Session):
        self.s = session
        self._cache: dict[tuple[str, str], tuple[int, float]] = {}

    def resolve(self, name: str, source: str, country: str = "", candidates: list[int] | None = None,
                create: bool = True, is_national: bool = False) -> tuple[int | None, float]:
        key = (source, f"{country}|{name}")
        if key in self._cache:
            return self._cache[key]
        norm = normalize(name)
        # 1) alias seen before for this source
        q = select(TeamAlias.team_id, TeamAlias.confidence).where(TeamAlias.alias_norm == norm)
        rows = self.s.execute(q).all()
        if candidates is not None:
            rows = [r for r in rows if r[0] in candidates] or rows
        if rows:
            team_id = rows[0][0]
            team = self.s.get(Team, team_id)
            if team is not None and (not country or team.country in ("", country) or candidates):
                res = (team_id, float(rows[0][1]))
                self._add_alias(norm, source, team_id, res[1])
                self._cache[key] = res
                return res
        # 2) fuzzy match within candidates
        if candidates:
            teams = self.s.execute(select(Team.id, Team.name).where(Team.id.in_(candidates))).all()
            best, score = None, 0.0
            for tid, tname in teams:
                r = difflib.SequenceMatcher(None, norm, normalize(tname)).ratio()
                tn = normalize(tname)
                if norm and tn and (norm in tn or tn in norm):
                    r = max(r, 0.9)
                if r > score:
                    best, score = tid, r
            if best is not None and score >= 0.80:
                self._add_alias(norm, source, best, round(score, 3))
                self._cache[key] = (best, round(score, 3))
                return self._cache[key]
        if not create:
            return (None, 0.0)
        team = self.s.execute(select(Team).where(Team.name == name, Team.country == country)).scalar_one_or_none()
        if team is None:
            team = Team(name=name, country=country, is_national=is_national)
            self.s.add(team)
            self.s.flush()
        self._add_alias(norm, source, team.id, 1.0)
        self._cache[key] = (team.id, 1.0)
        return self._cache[key]

    def _add_alias(self, norm: str, source: str, team_id: int, conf: float) -> None:
        exists = self.s.execute(select(TeamAlias.id).where(
            TeamAlias.alias_norm == norm, TeamAlias.source == source, TeamAlias.team_id == team_id)).first()
        if not exists:
            self.s.add(TeamAlias(alias_norm=norm, source=source, team_id=team_id, confidence=conf))
            self.s.flush()
