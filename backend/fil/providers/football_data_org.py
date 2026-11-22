"""football-data.org v4 client (free TIER_ONE plan).

Verified against the real API (2026-11-22) with a free account:
* 12 competitions: PL, ELC, PD, SA, BL1, FL1, DED, PPL, BSA, CL, EC, WC
* /competitions, /competitions/{c}/matches (seasons 2023-2026), /competitions/{c}/standings (TOTAL only),
  /competitions/{c}/scorers, /competitions/{c}/teams, /matches (date window ≤ 10 days)
* NOT on the free plan: odds (paid "Odds-Package"), seasons before 2023, other competitions (HTTP 403),
  lineups/match statistics (not in the response). Free-plan scores are delayed — never shown as live.

Security: the token is read only from the FOOTBALL_DATA_ORG_KEY environment variable, sent only in the
X-Auth-Token header, and never placed in URLs, cache keys, logs, errors or exports.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..catalog import BY_CODE, COMPETITIONS
from ..config import settings
from ..timeutil import to_utc_naive, utcnow
from .base import USER_AGENT, NotConfigured, Provider, ProviderError
from .footballdata_uk import MatchRecord

FDORG_STATUS = {"SCHEDULED": "scheduled", "TIMED": "scheduled", "IN_PLAY": "in_play", "PAUSED": "in_play",
                "FINISHED": "finished", "AWARDED": "finished", "POSTPONED": "postponed", "SUSPENDED": "postponed",
                "CANCELLED": "cancelled"}
FREE_SEASONS = (2023, 2024, 2025, 2026)
LEAGUE_CODES = ("PL", "ELC", "PD", "SA", "BL1", "FL1", "DED", "PPL", "BSA")
CUP_CODES = ("CL", "EC", "WC")


class AuthError(ProviderError):
    """Token missing/invalid — a configuration problem, not a transient failure."""


class Restricted(ProviderError):
    """HTTP 403: resource not included in the account's plan."""


class FootballDataOrg(Provider):
    key = "football_data_org"
    name = "football-data.org"
    kind = "fixtures, results, standings for 12 competitions (free plan; scores delayed)"
    base_url = "https://api.football-data.org/v4"
    license_note = ("Free plan with API token (FOOTBALL_DATA_ORG_KEY): 12 competitions, 10 requests/minute, seasons "
                    "2023+, no odds/lineups. Scores on the free plan are delayed, not live.")
    requires_key = True
    reliability = "high"
    min_interval_s = 6.2      # 10 req/min
    cache_ttl_s = 1800

    def __init__(self):
        super().__init__()
        self.available: int | None = None   # X-Requests-Available-Minute
        self.reset_s: int | None = None     # X-RequestCounter-Reset (seconds)
        self.requests = 0
        self.restricted: dict[str, str] = {}
        self.endpoints_ok: set[str] = set()
        self.sleep = time.sleep             # injectable for tests

    # ------------------------------------------------------------------ configuration
    @property
    def configured(self) -> bool:
        return bool(settings.football_data_org_key)

    def require_key(self) -> str:
        key = settings.football_data_org_key
        if not key:
            raise NotConfigured("football-data.org is not configured: environment variable FOOTBALL_DATA_ORG_KEY is "
                                "not set (add it as a GitHub Actions repository secret or in a local .env file)")
        return key

    def headers(self) -> dict:
        return {"User-Agent": USER_AGENT, "X-Auth-Token": self.require_key()}

    # ------------------------------------------------------------------ http
    def _read_rate_headers(self, headers) -> None:
        h = {k.lower(): v for k, v in headers.items()}
        for k in ("x-requests-available-minute", "x-requestsavailable", "x-requests-available"):
            if k in h:
                try:
                    self.available = int(h[k])
                except ValueError:
                    pass
        if "x-requestcounter-reset" in h:
            try:
                self.reset_s = int(h["x-requestcounter-reset"])
            except ValueError:
                pass

    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.time() - self._last_request)
        if self.available is not None and self.available <= 1:
            wait = max(wait, (self.reset_s or 60) + 1)  # quota exhausted: wait for the counter reset
        if wait > 0:
            self.sleep(min(wait, 65))

    def request(self, path: str, params: dict | None = None, ttl: int | None = None, retries: int = 4) -> tuple[dict, str, datetime]:
        """GET a v4 resource → (json, public_url, retrieved_at). Cache key never includes the token."""
        self.require_key()
        ttl = self.cache_ttl_s if ttl is None else ttl
        url = str(httpx.Request("GET", f"{self.base_url}{path}", params=params).url)
        cpath = self.cache_dir / hashlib.sha1(url.encode()).hexdigest()
        if ttl > 0 and cpath.exists() and time.time() - cpath.stat().st_mtime < ttl:
            return json.loads(cpath.read_text()), url, datetime.fromtimestamp(cpath.stat().st_mtime, timezone.utc).replace(tzinfo=None)
        last: Exception | None = None
        for attempt in range(retries):
            self._throttle()
            try:
                self._last_request = time.time()
                self.requests += 1
                with httpx.Client(timeout=30, follow_redirects=True, headers=self.headers()) as c:
                    r = c.get(url)
            except httpx.HTTPError as exc:  # downtime / timeout: back off and retry
                last = ProviderError(f"network error contacting football-data.org ({type(exc).__name__})")
                self.sleep(min(2 ** attempt * 3, 30))
                continue
            self._read_rate_headers(r.headers)
            if r.status_code == 429:
                ra = r.headers.get("Retry-After") or r.headers.get("X-RequestCounter-Reset") or "0"
                try:
                    wait = float(ra)
                except ValueError:
                    wait = 0
                self.available = 0
                self.sleep(min(max(wait, 2 ** attempt * 5), 65))
                last = ProviderError(f"rate limited (429) on {path}")
                continue
            body = self._json(r, path)
            if r.status_code == 200:
                if not isinstance(body, dict):
                    raise ProviderError(f"malformed response from {path}: expected an object")
                cpath.write_text(json.dumps(body))
                self.endpoints_ok.add(path.split("?")[0])
                return body, url, utcnow()
            msg = str((body or {}).get("message", "")) if isinstance(body, dict) else ""
            if r.status_code in (400, 401) and "token" in msg.lower():
                raise AuthError("football-data.org rejected the API token (HTTP %d: invalid token) — check the "
                                "FOOTBALL_DATA_ORG_KEY secret" % r.status_code)
            if r.status_code == 403:
                self.restricted[path] = "not included in the current plan (HTTP 403)"
                raise Restricted(f"{path}: not included in the current football-data.org plan (HTTP 403)")
            if r.status_code >= 500:
                last = ProviderError(f"football-data.org server error {r.status_code} on {path}")
                self.sleep(min(2 ** attempt * 3, 30))
                continue
            raise ProviderError(f"HTTP {r.status_code} on {path}: {msg[:120]}")
        if cpath.exists():  # all retries failed: serve the last good copy, labelled with its own time
            return (json.loads(cpath.read_text()), url,
                    datetime.fromtimestamp(cpath.stat().st_mtime, timezone.utc).replace(tzinfo=None))
        raise last or ProviderError(f"request failed: {path}")

    @staticmethod
    def _json(r, path):
        try:
            return r.json()
        except ValueError:
            if r.status_code == 200:
                raise ProviderError(f"malformed JSON from football-data.org {path}")
            return None

    # ------------------------------------------------------------------ endpoints
    def competitions(self) -> list[dict]:
        body, _, _ = self.request("/competitions", ttl=24 * 3600)
        return [{"code": c.get("code"), "name": c.get("name"), "plan": c.get("plan"), "type": c.get("type"),
                 "area": (c.get("area") or {}).get("name"),
                 "current_season": ((c.get("currentSeason") or {}).get("startDate") or "")[:4]}
                for c in body.get("competitions", []) if c.get("code")]

    def code_map(self) -> dict:
        return {c["sources"]["fdorg"]: c["code"] for c in COMPETITIONS if "fdorg" in c["sources"]}

    def _record(self, m: dict, comp: str, url: str, ts: datetime) -> MatchRecord | None:
        try:
            ht, at = m["homeTeam"], m["awayTeam"]
            home = ht.get("shortName") or ht.get("name")
            away = at.get("shortName") or at.get("name")
            ko = to_utc_naive(datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")))
        except (KeyError, TypeError, ValueError, AttributeError):
            return None
        if not home or not away:
            return None  # e.g. knockout slots with undecided teams
        status = FDORG_STATUS.get(m.get("status"), "unknown")
        score = m.get("score") or {}
        ft, hts = score.get("fullTime") or {}, score.get("halfTime") or {}
        # 90-minute score: for extra time/penalties football-data.org exposes regularTime
        extra_time = score.get("duration") in ("EXTRA_TIME", "PENALTY_SHOOTOUT")
        if extra_time and score.get("regularTime"):
            ft = score["regularTime"]
        if status == "finished" and extra_time:
            status = "finished_aet"  # 90-minute score of a match that went to extra time / penalties
        aliases = tuple(x for x in (("home", ht.get("name")), ("home", ht.get("tla")), ("away", at.get("name")),
                                    ("away", at.get("tla"))) if x[1])
        return MatchRecord(
            comp_code=comp, season=str(((m.get("season") or {}).get("startDate") or "")[:4]), home=home, away=away,
            kickoff_utc=ko, country=BY_CODE[comp]["country"], status=status if status != "in_play" else "scheduled",
            home_goals=ft.get("home") if status.startswith("finished") else None,
            away_goals=ft.get("away") if status.startswith("finished") else None,
            ht_home=hts.get("home") if status.startswith("finished") else None,
            ht_away=hts.get("away") if status.startswith("finished") else None,
            source_url=url, retrieved_at=ts, external_id=str(m.get("id")), aliases=aliases)

    def competition_matches(self, fd_code: str, season: int | None = None, ttl: int | None = None) -> list[MatchRecord]:
        comp = self.code_map().get(fd_code)
        if comp is None:
            return []
        params = {"season": season} if season else None
        body, url, ts = self.request(f"/competitions/{fd_code}/matches", params, ttl=ttl)
        return [r for r in (self._record(m, comp, url, ts) for m in body.get("matches", []) or []) if r]

    def matches(self, days_back: int = 3, days_forward: int = 7) -> list[MatchRecord]:
        """All plan competitions in a date window (one request; API maximum window is 10 days)."""
        today = utcnow().date()
        body, url, ts = self.request("/matches", {"dateFrom": str(today - timedelta(days=days_back)),
                                                  "dateTo": str(today + timedelta(days=days_forward))}, ttl=900)
        cmap = self.code_map()
        out = []
        self.in_play_seen = 0
        for m in body.get("matches", []) or []:
            comp = cmap.get((m.get("competition") or {}).get("code"))
            if comp:
                if FDORG_STATUS.get(m.get("status")) == "in_play":
                    self.in_play_seen += 1  # delayed score on the free plan: deliberately not stored as live
                r = self._record(m, comp, url, ts)
                if r:
                    out.append(r)
        return out

    def standings(self, fd_code: str) -> tuple[list[dict], str, str, datetime]:
        body, url, ts = self.request(f"/competitions/{fd_code}/standings", ttl=6 * 3600)
        season = str(((body.get("season") or {}).get("startDate") or "")[:4])
        rows = []
        for table in body.get("standings", []) or []:
            if table.get("type") != "TOTAL":
                continue
            for t in table.get("table", []) or []:
                try:
                    rows.append({"team": (t["team"].get("shortName") or t["team"].get("name")),
                                 "team_full": t["team"].get("name"), "group": table.get("group"),
                                 "position": int(t["position"]), "played": int(t["playedGames"]), "won": int(t["won"]),
                                 "draw": int(t["draw"]), "lost": int(t["lost"]), "goals_for": int(t["goalsFor"]),
                                 "goals_against": int(t["goalsAgainst"]), "points": int(t["points"]), "form": t.get("form")})
                except (KeyError, TypeError, ValueError):
                    continue
        return rows, season, url, ts

    def quota(self) -> dict:
        return {"requests_available_minute": self.available, "counter_reset_s": self.reset_s,
                "requests_this_run": self.requests, "restricted": self.restricted,
                "endpoints_ok": sorted(self.endpoints_ok)}
