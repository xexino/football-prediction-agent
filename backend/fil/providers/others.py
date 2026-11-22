"""Secondary providers.

* TheSportsDB (public test key "123"): fixture discovery & result cross-checks; the free key
  returns at most ~1-15 events per call, so it is a *discovery/verification* source only.
* International results dataset (github.com/martj42/international_results, CC0): national-team
  results since 1872, used for national-team Elo ratings and coverage.
* football-data.org (needs free key): fixtures/results for 12 competitions incl. Champions League.
* The Odds API (needs free key): bookmaker odds incl. Champions League and many leagues.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta

import pandas as pd

from ..catalog import BY_CODE, COMPETITIONS, INTL_TOURNAMENT
from ..config import settings
from ..timeutil import to_utc_naive, utcnow
from .base import NotConfigured, Provider, ProviderError
from .footballdata_uk import MatchRecord, _int, _price

TSDB_STATUS = {
    "NS": "scheduled", "FT": "finished", "AET": "finished", "PEN": "finished", "Match Finished": "finished",
    "PST": "postponed", "Postponed": "postponed", "CANC": "cancelled", "ABD": "abandoned", "SUSP": "postponed",
}


class TheSportsDB(Provider):
    key = "thesportsdb"
    name = "TheSportsDB (free test key)"
    kind = "fixture discovery, result cross-check"
    base_url = "https://www.thesportsdb.com/api/v1/json"
    license_note = "Free public test key '123' — heavily limited (≈1-15 events per request). Community-maintained data."
    reliability = "medium"
    min_interval_s = 3.0  # free test key is rate-limited; stay well under it
    cache_ttl_s = 3 * 3600

    def redact(self, url: str) -> str:
        return url.replace(f"/json/{settings.thesportsdb_key}/", "/json/<key>/")

    def _events(self, endpoint: str, params: dict, ttl: int | None = None) -> tuple[list, str, datetime]:
        res = self.get(f"{self.base_url}/{settings.thesportsdb_key}/{endpoint}", params=params, ttl=ttl)
        try:
            data = json.loads(res.text or "{}")
        except ValueError as exc:
            raise ProviderError(f"malformed JSON from {res.url}: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError(f"unexpected payload type from {res.url}")
        return (data.get("events") or data.get("results") or []), res.url, res.retrieved_at

    def _to_record(self, e: dict, comp_code: str, url: str, ts: datetime) -> MatchRecord | None:
        if (e.get("strSport") or "Soccer") != "Soccer" or not e.get("strHomeTeam"):
            return None
        stamp = e.get("strTimestamp")
        try:
            ko = to_utc_naive(datetime.fromisoformat(stamp)) if stamp else datetime.fromisoformat(f"{e['dateEvent']}T{(e.get('strTime') or '12:00:00')[:8]}")
        except (ValueError, KeyError):
            return None
        hg, ag = _int(e.get("intHomeScore")), _int(e.get("intAwayScore"))
        status = TSDB_STATUS.get(e.get("strStatus") or "", "scheduled")
        if (e.get("strPostponed") or "no").lower() == "yes":
            status = "postponed"
        if status == "scheduled" and hg is not None and ag is not None and ko < utcnow() - timedelta(hours=3):
            status = "finished"
        return MatchRecord(comp_code=comp_code, season=e.get("strSeason") or "", home=e["strHomeTeam"].strip(),
                           away=e["strAwayTeam"].strip(), kickoff_utc=ko, country=BY_CODE[comp_code]["country"],
                           status=status, home_goals=hg if status == "finished" else None,
                           away_goals=ag if status == "finished" else None, source_url=url, retrieved_at=ts,
                           external_id=e.get("idEvent"))

    def league_events(self, comp_code: str) -> list[MatchRecord]:
        lid = BY_CODE[comp_code]["sources"]["tsdb"]
        out = []
        for ep in ("eventsnextleague.php", "eventspastleague.php"):
            events, url, ts = self._events(ep, {"id": lid})
            out += [r for r in (self._to_record(e, comp_code, url, ts) for e in events) if r]
        return out


class InternationalResults(Provider):
    key = "intl_results"
    name = "International results dataset (martj42, GitHub)"
    kind = "national-team historical results"
    base_url = "https://raw.githubusercontent.com/martj42/international_results/master"
    license_note = "CC0 public-domain dataset maintained on GitHub; updated irregularly after match days."
    reliability = "high"
    cache_ttl_s = 12 * 3600

    def results(self, since_year: int = 2014) -> list[MatchRecord]:
        res = self.get(f"{self.base_url}/results.csv")
        df = pd.read_csv(io.StringIO(res.text), dtype=str)
        out = []
        for row in df.to_dict("records"):
            if not row.get("date") or row["date"][:4] < str(since_year):
                continue
            comp = INTL_TOURNAMENT.get(row.get("tournament", ""))
            if comp is None:
                comp = "INTFR" if row.get("tournament") == "Friendly" else None
            if comp is None:
                continue
            hg, ag = _int(row.get("home_score")), _int(row.get("away_score"))
            out.append(MatchRecord(
                comp_code=comp, season=row["date"][:4], home=row["home_team"], away=row["away_team"],
                kickoff_utc=datetime.fromisoformat(row["date"] + "T18:00:00"), country="",
                status="finished" if hg is not None and ag is not None else "scheduled",
                home_goals=hg, away_goals=ag, neutral=str(row.get("neutral")).upper() == "TRUE",
                source_url=res.url, retrieved_at=res.retrieved_at,
            ))
        return out


FDORG_STATUS = {"SCHEDULED": "scheduled", "TIMED": "scheduled", "IN_PLAY": "live", "PAUSED": "live",
                "FINISHED": "finished", "AWARDED": "finished", "POSTPONED": "postponed", "SUSPENDED": "postponed",
                "CANCELLED": "cancelled"}


class FootballDataOrg(Provider):
    key = "football_data_org"
    name = "football-data.org"
    kind = "fixtures, results (12 competitions on free tier)"
    base_url = "https://api.football-data.org/v4"
    license_note = "Free tier with API key: 12 competitions, 10 requests/minute. Requires FOOTBALL_DATA_ORG_KEY."
    requires_key = True
    reliability = "high"
    min_interval_s = 6.5
    cache_ttl_s = 1800

    @property
    def configured(self) -> bool:
        return bool(settings.football_data_org_key)

    def headers(self) -> dict:
        return {**super().headers(), "X-Auth-Token": settings.football_data_org_key}

    def matches(self, days_back: int = 3, days_forward: int = 7) -> list[MatchRecord]:
        if not self.configured:
            raise NotConfigured("FOOTBALL_DATA_ORG_KEY not set")
        code_map = {c["sources"]["fdorg"]: c["code"] for c in COMPETITIONS if "fdorg" in c["sources"]}
        today = utcnow().date()
        res = self.get(f"{self.base_url}/matches", params={
            "dateFrom": str(today - timedelta(days=days_back)), "dateTo": str(today + timedelta(days=days_forward))})
        out = []
        for m in json.loads(res.text).get("matches", []):
            comp = code_map.get((m.get("competition") or {}).get("code"))
            if not comp:
                continue
            ft = (m.get("score") or {}).get("fullTime") or {}
            ht = (m.get("score") or {}).get("halfTime") or {}
            status = FDORG_STATUS.get(m.get("status"), "unknown")
            out.append(MatchRecord(
                comp_code=comp, season=str(((m.get("season") or {}).get("startDate") or "")[:4]),
                home=(m["homeTeam"].get("shortName") or m["homeTeam"]["name"]),
                away=(m["awayTeam"].get("shortName") or m["awayTeam"]["name"]),
                kickoff_utc=to_utc_naive(datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))),
                country=BY_CODE[comp]["country"], status=status,
                home_goals=ft.get("home") if status == "finished" else None,
                away_goals=ft.get("away") if status == "finished" else None,
                ht_home=ht.get("home"), ht_away=ht.get("away"),
                source_url=res.url, retrieved_at=res.retrieved_at, external_id=str(m.get("id")),
            ))
        self.last_quota = {"requests_available_minute": res.headers.get("x-requests-available-minute")}
        return out


ODDS_API_SPORTS = {
    "UCL": "soccer_uefa_champs_league", "UEL": "soccer_uefa_europa_league", "UECL": "soccer_uefa_europa_conference_league",
    "ENG1": "soccer_epl", "ENG2": "soccer_efl_champ", "ITA1": "soccer_italy_serie_a", "ESP1": "soccer_spain_la_liga",
    "GER1": "soccer_germany_bundesliga", "FRA1": "soccer_france_ligue_one", "POR1": "soccer_portugal_primeira_liga",
    "NED1": "soccer_netherlands_eredivisie", "BEL1": "soccer_belgium_first_div", "TUR1": "soccer_turkey_super_league",
    "SCO1": "soccer_spl", "BRA1": "soccer_brazil_campeonato", "ARG1": "soccer_argentina_primera_division",
}


class OddsAPI(Provider):
    key = "the_odds_api"
    name = "The Odds API"
    kind = "pre-match bookmaker odds (h2h, totals)"
    base_url = "https://api.the-odds-api.com/v4"
    license_note = "Free tier with API key: 500 credits/month. Requires ODDS_API_KEY."
    requires_key = True
    reliability = "high"
    min_interval_s = 1.0
    cache_ttl_s = 3 * 3600

    @property
    def configured(self) -> bool:
        return bool(settings.odds_api_key)

    def redact(self, url: str) -> str:
        import re

        return re.sub(r"apiKey=[^&]+", "apiKey=<redacted>", url)

    def odds(self, comp_code: str) -> list[MatchRecord]:
        if not self.configured:
            raise NotConfigured("ODDS_API_KEY not set")
        sport = ODDS_API_SPORTS[comp_code]
        res = self.get(f"{self.base_url}/sports/{sport}/odds", params={
            "apiKey": settings.odds_api_key, "regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"})
        out = []
        for ev in json.loads(res.text):
            home, away = ev["home_team"], ev["away_team"]
            odds = []
            for bk in ev.get("bookmakers", []):
                m: dict = {}
                for mk in bk.get("markets", []):
                    for o in mk.get("outcomes", []):
                        if mk["key"] == "h2h":
                            sel = "home" if o["name"] == home else "away" if o["name"] == away else "draw"
                            m[sel] = _price(o.get("price"))
                        elif mk["key"] == "totals" and float(o.get("point", 0)) == 2.5:
                            m["over25" if o["name"] == "Over" else "under25"] = _price(o.get("price"))
                if m:
                    odds.append((bk.get("title", bk.get("key", "?"))[:32], "pre_match", m))
            out.append(MatchRecord(
                comp_code=comp_code, season="", home=home, away=away,
                kickoff_utc=to_utc_naive(datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))),
                country=BY_CODE[comp_code]["country"], odds=odds, source_url=res.url,
                retrieved_at=res.retrieved_at, external_id=ev.get("id")))
        self.last_quota = {"requests_remaining": res.headers.get("x-requests-remaining"),
                           "requests_used": res.headers.get("x-requests-used")}
        return out


class APIFootball(Provider):
    """Registered so the dashboard shows it as an available-but-unconfigured upgrade path
    (injuries, lineups, African leagues, live scores). No calls are made without a key."""

    key = "api_football"
    name = "API-Football"
    kind = "fixtures, injuries, lineups, live scores (broad incl. Africa)"
    base_url = "https://v3.football.api-sports.io"
    license_note = "Free tier with API key: 100 requests/day. Requires API_FOOTBALL_KEY. Adapter not yet implemented."
    requires_key = True

    @property
    def configured(self) -> bool:
        return bool(settings.api_football_key)
