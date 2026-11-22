"""football-data.co.uk adapter.

Free CSV files (no key) with historical results, match statistics (shots, corners, cards and,
from 2026/27, xG), pre-match and closing odds from several bookmakers, and a weekly
fixtures file with pre-match odds for upcoming games. Data is refreshed by the site a few
times per week (it is NOT live). Times in the files are UK local time.
Licence: free to use for personal/non-commercial research; attribution to football-data.co.uk.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from ..catalog import FD_UK_DIV, FD_UK_LEAGUE, FD_UK_NEW
from ..timeutil import local_to_utc, utcnow
from .base import Provider, ProviderError

BASE = "https://www.football-data.co.uk"

BOOKMAKER_LABELS = {
    "B365": "Bet365", "BW": "bwin", "PS": "Pinnacle", "BFE": "Betfair Exchange", "BFD": "Betfred",
    "BV": "BetVictor", "PP": "Paddy Power", "SKB": "Sky Bet", "WH": "William Hill",
    "Max": "Market maximum", "Avg": "Market average",
}
# bookmakers we keep (1X2 code, OU/AH code)
KEEP = [("B365", "B365"), ("PS", "P"), ("BFE", "BFE"), ("BW", "BW"), ("Max", "Max"), ("Avg", "Avg")]


@dataclass
class MatchRecord:
    comp_code: str
    season: str
    home: str
    away: str
    kickoff_utc: datetime
    country: str
    status: str = "scheduled"
    home_goals: int | None = None
    away_goals: int | None = None
    ht_home: int | None = None
    ht_away: int | None = None
    stats: dict = field(default_factory=dict)
    odds: list = field(default_factory=list)  # list of (bookmaker, kind, {market fields})
    source_url: str = ""
    retrieved_at: datetime | None = None
    neutral: bool = False
    external_id: str | None = None
    aliases: tuple = ()  # alternative names from the same provider (e.g. full name, short name, TLA)


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _int(v):
    f = _num(v)
    return None if f is None else int(round(f))


def _price(v):
    f = _num(v)
    return f if f is not None and 1.01 <= f <= 1000 else None


def _ko(row: dict):
    """Kickoff in UTC, or None for rows with an invalid/missing date (skipped and counted)."""
    try:
        return local_to_utc(row["Date"], row.get("Time"))
    except (ValueError, KeyError, TypeError):
        return None


def extract_odds(row: dict) -> list:
    out = []
    for kind, c in (("pre_match", ""), ("closing", "C")):
        line = _num(row.get("AHCh" if c else "AHh"))
        for bk1, bk2 in KEEP:
            m = {
                "home": _price(row.get(f"{bk1}{c}H")),
                "draw": _price(row.get(f"{bk1}{c}D")),
                "away": _price(row.get(f"{bk1}{c}A")),
                "over25": _price(row.get(f"{bk2}{c}>2.5")),
                "under25": _price(row.get(f"{bk2}{c}<2.5")),
                "ah_home": _price(row.get(f"{bk2}{c}AHH")),
                "ah_away": _price(row.get(f"{bk2}{c}AHA")),
            }
            m["ah_line"] = line if (m["ah_home"] and m["ah_away"]) else None
            if any(v is not None for k, v in m.items() if k != "ah_line"):
                out.append((bk1, kind, m))
    return out


def extract_stats(row: dict) -> dict:
    mapping = {
        "home_xg": "HxG", "away_xg": "AxG", "home_shots": "HS", "away_shots": "AS", "home_sot": "HST",
        "away_sot": "AST", "home_corners": "HC", "away_corners": "AC", "home_fouls": "HF", "away_fouls": "AF",
        "home_yellow": "HY", "away_yellow": "AY", "home_red": "HR", "away_red": "AR",
    }
    st = {}
    for k, col in mapping.items():
        v = _num(row.get(col))
        if v is not None:
            st[k] = v if "xg" in k else int(v)
    return st


def season_codes(n: int, today: datetime | None = None) -> list[str]:
    today = today or utcnow()
    start = today.year if today.month >= 7 else today.year - 1
    return [f"{(y) % 100:02d}{(y + 1) % 100:02d}" for y in range(start - n + 1, start + 1)]


class FootballDataUK(Provider):
    key = "football_data_uk"
    name = "football-data.co.uk"
    kind = "results, statistics, xG, pre-match & closing odds, weekly fixtures"
    base_url = BASE
    license_note = "Free CSV downloads for non-commercial research; attribution: football-data.co.uk. Updated ~2x/week (not live)."
    reliability = "high"
    min_interval_s = 1.5
    cache_ttl_s = 6 * 3600
    invalid_rows = 0

    def _read_csv(self, url: str, ttl: int | None = None):
        res = self.get(url, ttl=ttl)
        if res.text.lstrip().lower().startswith(("<!doctype", "<html")):
            raise ProviderError(f"expected CSV but got HTML from {res.url}")
        try:
            df = pd.read_csv(io.StringIO(res.text), dtype=str, on_bad_lines="skip")
        except Exception as exc:  # pandas raises several parser/empty-data errors
            raise ProviderError(f"malformed CSV from {res.url}: {exc}") from exc
        df.columns = [c.strip().lstrip("﻿") for c in df.columns]
        df = df.dropna(how="all")
        return df, res

    # ------------------------------------------------------------------ historical / current season results
    def main_league_results(self, div: str, season: str, ttl: int | None = None) -> list[MatchRecord]:
        from ..catalog import BY_CODE

        code = FD_UK_DIV[div]
        url = f"{BASE}/mmz4281/{season}/{div}.csv"
        df, res = self._read_csv(url, ttl)
        recs = []
        for row in df.to_dict("records"):
            if not row.get("HomeTeam") or not row.get("Date"):
                continue
            ko = _ko(row)
            if ko is None:
                self.invalid_rows += 1
                continue
            fthg, ftag = _int(row.get("FTHG")), _int(row.get("FTAG"))
            recs.append(MatchRecord(
                comp_code=code, season=f"20{season[:2]}/{season[2:]}", home=row["HomeTeam"].strip(),
                away=row["AwayTeam"].strip(), kickoff_utc=ko,
                country=BY_CODE[code]["country"],
                status="finished" if fthg is not None and ftag is not None else "scheduled",
                home_goals=fthg, away_goals=ftag, ht_home=_int(row.get("HTHG")), ht_away=_int(row.get("HTAG")),
                stats=extract_stats(row), odds=extract_odds(row), source_url=res.url, retrieved_at=res.retrieved_at,
            ))
        return recs

    def extra_league_results(self, code3: str, since_year: int, ttl: int | None = None) -> list[MatchRecord]:
        from ..catalog import BY_CODE

        code = FD_UK_NEW[code3]
        url = f"{BASE}/new/{code3}.csv"
        df, res = self._read_csv(url, ttl)
        recs = []
        for row in df.to_dict("records"):
            if not row.get("Home") or not row.get("Date"):
                continue
            ko = _ko(row)
            if ko is None:
                self.invalid_rows += 1
                continue
            if ko.year < since_year:
                continue
            hg, ag = _int(row.get("HG")), _int(row.get("AG"))
            odds = []
            for bk in ("PS", "Max", "Avg", "BFE", "B365"):
                m = {"home": _price(row.get(f"{bk}CH")), "draw": _price(row.get(f"{bk}CD")), "away": _price(row.get(f"{bk}CA"))}
                if any(m.values()):
                    odds.append((bk, "closing", m))
            recs.append(MatchRecord(
                comp_code=code, season=str(row.get("Season", "")), home=row["Home"].strip(), away=row["Away"].strip(),
                kickoff_utc=ko, country=BY_CODE[code]["country"],
                status="finished" if hg is not None and ag is not None else "scheduled",
                home_goals=hg, away_goals=ag, odds=odds, source_url=res.url, retrieved_at=res.retrieved_at,
            ))
        return recs

    # ------------------------------------------------------------------ upcoming fixtures with pre-match odds
    def upcoming_fixtures(self, ttl: int = 1800) -> list[MatchRecord]:
        from ..catalog import BY_CODE

        recs = []
        df, res = self._read_csv(f"{BASE}/fixtures.csv", ttl)
        for row in df.to_dict("records"):
            code = FD_UK_DIV.get((row.get("Div") or "").strip())
            if not code or not row.get("HomeTeam") or _ko(row) is None:
                continue
            recs.append(MatchRecord(
                comp_code=code, season="", home=row["HomeTeam"].strip(), away=row["AwayTeam"].strip(),
                kickoff_utc=_ko(row), country=BY_CODE[code]["country"],
                odds=[o for o in extract_odds(row) if o[1] == "pre_match"], source_url=res.url, retrieved_at=res.retrieved_at,
            ))
        df, res = self._read_csv(f"{BASE}/new_league_fixtures.csv", ttl)
        for row in df.to_dict("records"):
            code = FD_UK_LEAGUE.get(f"{(row.get('Country') or '').strip()}|{(row.get('League') or '').strip()}")
            if not code or not row.get("Home") or _ko(row) is None:
                continue
            odds = []
            for bk in ("PS", "Max", "Avg", "BFE", "B365"):
                m = {"home": _price(row.get(f"{bk}H")), "draw": _price(row.get(f"{bk}D")), "away": _price(row.get(f"{bk}A"))}
                if any(m.values()):
                    odds.append((bk, "pre_match", m))
            recs.append(MatchRecord(
                comp_code=code, season="", home=row["Home"].strip(), away=row["Away"].strip(),
                kickoff_utc=_ko(row), country=BY_CODE[code]["country"],
                odds=odds, source_url=res.url, retrieved_at=res.retrieved_at,
            ))
        return recs
