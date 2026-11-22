"""Offline parser tests for provider adapters (no network)."""
from datetime import datetime

from fil.providers.base import FetchResult
from fil.providers.footballdata_uk import FootballDataUK, season_codes

RESULTS_CSV = (
    "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,HxG,AxG,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,"
    "B365H,B365D,B365A,BFEH,BFED,BFEA,AvgH,AvgD,AvgA,B365>2.5,B365<2.5,AHh,B365AHH,B365AHA,B365CH,B365CD,B365CA,AHCh,B365CAHH,B365CAHA\n"
    "E0,23/11/2026,20:00,Brentford,Everton,2,1,H,1,0,H,X,1.7,0.9,14,8,6,3,10,12,7,3,1,2,0,0,"
    "2.15,3.5,3.3,2.24,3.6,3.5,2.12,3.51,3.26,1.73,2.1,-0.25,1.88,1.98,2.0,3.6,3.6,-0.5,2.02,1.86\n"
    "E0,24/11/2026,,Arsenal,Spurs,,,,,,,,,,,,,,,,,,,,,,1.5,4.2,6.0,,,,,,,,,,,,,,,,,\n"
)
FIXTURES_CSV = "﻿Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\nE0,28/11/2026,15:00,Chelsea,Leeds,1.4,4.8,7.5\nZZ,28/11/2026,15:00,X,Y,2,3,4\n"
NEW_FIX_CSV = "﻿Country,League,Date,Time,Home,Away,PSH,PSD,PSA\nBrazil,Serie A,25/11/2026,23:00,Santos,Gremio,1.9,3.4,4.1\n"


def _fake(texts):
    def get(self, url, params=None, ttl=None, retries=3):
        for k, v in texts.items():
            if url.endswith(k):
                return FetchResult(v, url, datetime(2026, 11, 22, 12))
        raise AssertionError(url)
    return get


def test_parse_results(monkeypatch):
    monkeypatch.setattr(FootballDataUK, "get", _fake({"E0.csv": RESULTS_CSV}))
    recs = FootballDataUK().main_league_results("E0", "2627")
    assert len(recs) == 2
    r = recs[0]
    assert (r.comp_code, r.home, r.away, r.home_goals, r.away_goals, r.status) == ("ENG1", "Brentford", "Everton", 2, 1, "finished")
    assert r.kickoff_utc == datetime(2026, 11, 23, 20, 0)  # GMT in November
    assert r.stats["home_xg"] == 1.7 and r.stats["home_corners"] == 7
    kinds = {(b, k) for b, k, _ in r.odds}
    assert ("B365", "pre_match") in kinds and ("B365", "closing") in kinds
    pre = next(m for b, k, m in r.odds if b == "B365" and k == "pre_match")
    clo = next(m for b, k, m in r.odds if b == "B365" and k == "closing")
    assert pre["ah_line"] == -0.25 and clo["ah_line"] == -0.5 and pre["under25"] == 2.1
    assert recs[1].status == "scheduled" and recs[1].home_goals is None  # unplayed row, default 15:00 UK


def test_parse_fixtures(monkeypatch):
    monkeypatch.setattr(FootballDataUK, "get", _fake({"/fixtures.csv": FIXTURES_CSV, "new_league_fixtures.csv": NEW_FIX_CSV}))
    recs = FootballDataUK().upcoming_fixtures()
    assert [r.comp_code for r in recs] == ["ENG1", "BRA1"]  # unknown division ignored
    assert recs[1].odds[0][0] == "PS" and recs[1].odds[0][2]["home"] == 1.9


def test_season_codes():
    assert season_codes(2, datetime(2026, 11, 1)) == ["2526", "2627"]
    assert season_codes(1, datetime(2026, 3, 1)) == ["2526"]
