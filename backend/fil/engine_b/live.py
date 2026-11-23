"""Live match mode for Engine B: normalized multi-provider live data + in-play predictions.

Providers implement `LiveProvider.live_matches() -> list[LiveMatch]` and declare `capabilities`.
Source priority (documented in docs/LIVE_DATA.md): api_football (events, minute, statistics)
> football_data_org (score/status only; DELAYED on the free plan). Data from different providers is
never merged into one snapshot: each snapshot names exactly one provider.

Labels: LIVE (provider gives the minute and data is < 3 min old), DELAYED (score without reliable
minute, or older than 3 min), STALE (> 30 min since provider update) — STALE data never produces a
live prediction. Missing statistics are omitted, never written as zero.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.stats import poisson
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..config import settings
from ..db import EBLiveEvent, EBLiveSnapshot, EBPrediction, Fixture, log, session_scope
from ..timeutil import to_utc_naive, utcnow


@dataclass
class LiveMatch:
    provider: str
    provider_event_id: str
    comp_code: str | None
    home: str
    away: str
    kickoff_utc: datetime
    status: str                     # live / halftime / finished / scheduled / postponed / unknown
    minute: int | None
    minute_source: str              # provider / estimated / unknown
    home_goals: int | None
    away_goals: int | None
    stats: dict = field(default_factory=dict)     # {"corners": {"home": 3, "away": 1}, ...} only supplied fields
    events: list = field(default_factory=list)    # [{"key","minute","type","side","player","detail"}]
    provider_updated_at: datetime | None = None
    retrieved_at: datetime | None = None
    fixture_id: int | None = None                 # when the provider event is already linked


class LiveProvider:
    name = "base"
    priority = 99
    capabilities: dict = {}

    @property
    def configured(self) -> bool:
        return False

    def live_matches(self) -> list[LiveMatch]:
        raise NotImplementedError


# ---------------------------------------------------------------------------- football-data.org (free plan)
class FootballDataOrgLive(LiveProvider):
    name = "football_data_org"
    priority = 2
    capabilities = {"score": True, "status": True, "minute": False, "events": False, "statistics": False,
                    "lineups": False, "label": "DELAYED score/status only on the free plan (verified 2026-11-23)"}

    @property
    def configured(self) -> bool:
        return bool(settings.football_data_org_key)

    def live_matches(self) -> list[LiveMatch]:
        from ..providers.football_data_org import FootballDataOrg

        p = FootballDataOrg()
        body, url, ts = p.request("/matches", {"status": "IN_PLAY,PAUSED"}, ttl=60)
        cmap = p.code_map()
        out = []
        for m in body.get("matches", []) or []:
            try:
                ft = (m.get("score") or {}).get("fullTime") or {}
                upd = m.get("lastUpdated")
                out.append(LiveMatch(
                    provider=self.name, provider_event_id=str(m["id"]), comp_code=cmap.get((m.get("competition") or {}).get("code")),
                    home=m["homeTeam"].get("shortName") or m["homeTeam"]["name"], away=m["awayTeam"].get("shortName") or m["awayTeam"]["name"],
                    kickoff_utc=to_utc_naive(datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))),
                    status="halftime" if m.get("status") == "PAUSED" else "live",
                    minute=m.get("minute") if isinstance(m.get("minute"), int) else None,
                    minute_source="provider" if isinstance(m.get("minute"), int) else "unknown",
                    home_goals=ft.get("home"), away_goals=ft.get("away"),
                    provider_updated_at=to_utc_naive(datetime.fromisoformat(upd.replace("Z", "+00:00"))) if upd else None,
                    retrieved_at=ts))
            except (KeyError, TypeError, ValueError):
                continue
        return out


# ---------------------------------------------------------------------------- API-Football (awaiting key)
APIF_STATUS = {"1H": "live", "2H": "live", "ET": "live", "BT": "live", "P": "live", "LIVE": "live", "HT": "halftime",
               "FT": "finished", "AET": "finished", "PEN": "finished", "PST": "postponed", "CANC": "cancelled",
               "ABD": "abandoned", "SUSP": "postponed", "INT": "live", "NS": "scheduled", "TBD": "scheduled"}
APIF_STAT_MAP = {"Corner Kicks": "corners", "Shots on Goal": "shots_on_target", "Total Shots": "shots",
                 "Ball Possession": "possession", "Fouls": "fouls", "Offsides": "offsides", "Yellow Cards": "yellow_cards",
                 "Red Cards": "red_cards", "expected_goals": "xg"}


class APIFootballLive(LiveProvider):
    """API-Football v3 (api-sports.io). Free plan: 100 requests/day, all endpoints (per provider docs).
    Budget here: 1 request per poll for all live fixtures (events included) + statistics for at most
    `max_stat_calls` fixtures we cover."""

    name = "api_football"
    priority = 1
    base = "https://v3.football.api-sports.io"
    capabilities = {"score": True, "status": True, "minute": True, "events": True, "statistics": True, "lineups": True,
                    "label": "LIVE (provider minute + events); statistics for covered fixtures"}
    max_stat_calls = 3

    def __init__(self):
        self.remaining = None

    @property
    def configured(self) -> bool:
        return bool(settings.api_football_key)

    def _get(self, path, params):
        import httpx

        from ..providers.base import ProviderError

        if not self.configured:
            from ..providers.base import NotConfigured

            raise NotConfigured("API_FOOTBALL_KEY is not set (GitHub Actions secret / .env)")
        with httpx.Client(timeout=20, headers={"x-apisports-key": settings.api_football_key}) as c:
            r = c.get(self.base + path, params=params)
        self.remaining = r.headers.get("x-ratelimit-requests-remaining", self.remaining)
        if r.status_code == 429:
            raise ProviderError("API-Football rate limit reached (429)")
        if r.status_code != 200:
            raise ProviderError(f"API-Football HTTP {r.status_code} on {path}")
        try:
            body = r.json()
        except ValueError as exc:
            raise ProviderError("malformed JSON from API-Football") from exc
        errs = body.get("errors")
        if errs:
            raise ProviderError(f"API-Football error: {str(errs)[:160]}")  # e.g. invalid key / plan limits
        return body

    def live_matches(self) -> list[LiveMatch]:
        from ..catalog import APIF_LEAGUE

        body = self._get("/fixtures", {"live": "all"})
        now = utcnow()
        out = []
        for it in body.get("response", []) or []:
            try:
                fx, lg, tm, gl = it["fixture"], it["league"], it["teams"], it["goals"]
                st = fx.get("status") or {}
                ev = []
                for e in it.get("events") or []:
                    side = "home" if (e.get("team") or {}).get("id") == tm["home"].get("id") else "away"
                    minute = (e.get("time") or {}).get("elapsed")
                    key = f"{fx['id']}:{minute}:{(e.get('time') or {}).get('extra')}:{e.get('type')}:{e.get('detail')}:{(e.get('player') or {}).get('id')}"
                    ev.append({"key": key, "minute": minute, "type": (e.get("type") or "").lower(), "side": side,
                               "player": (e.get("player") or {}).get("name"), "detail": e.get("detail")})
                out.append(LiveMatch(
                    provider=self.name, provider_event_id=str(fx["id"]), comp_code=APIF_LEAGUE.get(lg.get("id")),
                    home=tm["home"]["name"], away=tm["away"]["name"],
                    kickoff_utc=to_utc_naive(datetime.fromisoformat(fx["date"])),
                    status=APIF_STATUS.get(st.get("short"), "unknown"), minute=st.get("elapsed"),
                    minute_source="provider" if st.get("elapsed") is not None else "unknown",
                    home_goals=gl.get("home"), away_goals=gl.get("away"), events=ev, provider_updated_at=now, retrieved_at=now))
            except (KeyError, TypeError, ValueError):
                continue
        for lm in [m for m in out if m.comp_code][: self.max_stat_calls]:
            try:
                st = self._get("/fixtures/statistics", {"fixture": lm.provider_event_id})
                lm.stats = parse_apif_statistics(st)
            except Exception as exc:  # statistics are optional; never fabricate them
                log("WARNING", "live", f"API-Football statistics unavailable for {lm.provider_event_id}: {type(exc).__name__}")
        return out


def parse_apif_statistics(body: dict) -> dict:
    stats = {}
    resp = body.get("response") or []
    if len(resp) != 2:
        return stats
    for side, team in zip(("home", "away"), resp):
        for item in team.get("statistics") or []:
            key = APIF_STAT_MAP.get(item.get("type"))
            val = item.get("value")
            if key is None or val is None:  # missing statistic stays missing (never zero)
                continue
            if isinstance(val, str) and val.endswith("%"):
                val = float(val[:-1])
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            stats.setdefault(key, {})[side] = val
    return {k: v for k, v in stats.items() if len(v) == 2}


def providers() -> list[LiveProvider]:
    return sorted([APIFootballLive(), FootballDataOrgLive()], key=lambda p: p.priority)


# ---------------------------------------------------------------------------- in-play model
def live_probabilities(lh: float, la: float, minute: int, hg: int, ag: int, reds_home: int = 0, reds_away: int = 0) -> dict:
    """Remaining goals ~ Poisson(pre-match rate × remaining share), adjusted for red cards.
    Red-card factors (0.75 for the team down a man, 1.20 for the opponent) are approximations
    and are labelled as such in the snapshot."""
    remaining = max(0.0, (94 - min(minute, 94)) / 94)
    fh = (0.75 ** reds_home) * (1.20 ** reds_away)
    fa = (0.75 ** reds_away) * (1.20 ** reds_home)
    rh, ra = lh * remaining * fh, la * remaining * fa
    n = 10
    m = np.outer(poisson.pmf(np.arange(n), rh), poisson.pmf(np.arange(n), ra))
    m /= m.sum()
    i, j = np.indices(m.shape)
    fh_, fa_ = i + hg, j + ag
    res = {"1X2": {"home": float(m[fh_ > fa_].sum()), "draw": float(m[fh_ == fa_].sum()), "away": float(m[fh_ < fa_].sum())},
           "BTTS": {"yes": float(m[(fh_ > 0) & (fa_ > 0)].sum())},
           "remaining_expected_goals": {"home": rh, "away": ra},
           "next_goal": {"home": rh / (rh + ra) * (1 - float(m[0, 0])) if rh + ra > 0 else 0.0,
                         "away": ra / (rh + ra) * (1 - float(m[0, 0])) if rh + ra > 0 else 0.0, "none": float(m[0, 0])}}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        res[f"OU{str(line).replace('.', '')}"] = {"over": float(m[(fh_ + fa_) > line].sum())}
    res["assumptions"] = "remaining-time Poisson from Engine B pre-match rates; red-card factors approximate"
    return res


def label_for(lm: LiveMatch, now: datetime) -> tuple[str, float | None]:
    ref = lm.provider_updated_at or lm.retrieved_at
    fresh = (now - ref).total_seconds() if ref else None
    if fresh is None or fresh > 1800 or (now - lm.kickoff_utc) > timedelta(hours=3, minutes=30):
        return "STALE", fresh
    if lm.minute_source == "provider" and fresh <= 180:
        return "LIVE", fresh
    return "DELAYED", fresh


def _link_fixture(s, lm: LiveMatch) -> int | None:
    if lm.fixture_id:
        return lm.fixture_id
    from sqlalchemy import func

    fx = s.scalars(select(Fixture).where(func.json_extract(Fixture.external_ids, f"$.{lm.provider}") == lm.provider_event_id)).first()
    if fx:
        return fx.id
    if lm.comp_code is None:
        return None
    from ..ingest import Ingestor
    from ..providers.footballdata_uk import MatchRecord
    from ..catalog import BY_CODE

    ing = Ingestor(s, lm.provider)
    f = ing.add(MatchRecord(comp_code=lm.comp_code, season="", home=lm.home, away=lm.away, kickoff_utc=lm.kickoff_utc,
                            country=BY_CODE[lm.comp_code]["country"], external_id=lm.provider_event_id,
                            retrieved_at=lm.retrieved_at, source_url=lm.provider))
    return f.id if f else None


def poll() -> dict:
    """One polling cycle over every configured live provider. Stores a snapshot only when the
    relevant inputs changed (score, status, minute bucket, red cards, statistics)."""
    now = utcnow()
    out = {"providers": {}, "snapshots": 0, "events": 0, "live_predictions": 0}
    for prov in providers():
        if not prov.configured:
            out["providers"][prov.name] = "awaiting configuration"
            continue
        try:
            matches = prov.live_matches()
        except Exception as exc:
            out["providers"][prov.name] = f"error: {type(exc).__name__}: {str(exc)[:120]}"
            log("WARNING", "live", f"{prov.name}: {type(exc).__name__}: {exc}")
            continue
        out["providers"][prov.name] = {"matches": len(matches), "capabilities": prov.capabilities}
        with session_scope() as s:
            for lm in matches:
                fid = _link_fixture(s, lm)
                if fid is None:
                    continue
                label, fresh = label_for(lm, now)
                reds = {"home": 0, "away": 0}
                for e in lm.events:
                    if e["type"] == "card" and "red" in (e.get("detail") or "").lower():
                        reds[e["side"]] += 1
                    vals = dict(fixture_id=fid, provider=lm.provider, event_key=e["key"], minute=e["minute"],
                                event_type=e["type"], side=e["side"], player=e["player"], detail=e["detail"], retrieved_at=now)
                    out["events"] += s.execute(sqlite_insert(EBLiveEvent).values(**vals).on_conflict_do_nothing()).rowcount
                probs, mv = None, None
                pre = s.scalars(select(EBPrediction).where(EBPrediction.fixture_id == fid).order_by(EBPrediction.revision.desc())).first()
                if (pre is not None and label != "STALE" and lm.minute is not None and lm.home_goals is not None
                        and lm.status == "live"):
                    eg = pre.markets["EXPECTED_GOALS"]
                    probs = live_probabilities(eg["home"], eg["away"], lm.minute, lm.home_goals, lm.away_goals,
                                               reds["home"], reds["away"])
                    mv = pre.model_version_id
                key = json.dumps({"st": lm.status, "m": None if lm.minute is None else lm.minute // 5, "g": [lm.home_goals, lm.away_goals],
                                  "r": reds, "s": lm.stats, "lab": label}, sort_keys=True)
                vals = dict(fixture_id=fid, created_at=now, provider=lm.provider, provider_event_id=lm.provider_event_id,
                            status=lm.status, minute=lm.minute, minute_source=lm.minute_source, home_goals=lm.home_goals,
                            away_goals=lm.away_goals, stats=lm.stats, provider_updated_at=lm.provider_updated_at,
                            freshness_s=fresh, data_label=label, model_version_id=mv, probs=probs,
                            input_hash=hashlib.sha1(key.encode()).hexdigest())
                r = s.execute(sqlite_insert(EBLiveSnapshot).values(**vals).on_conflict_do_nothing())
                out["snapshots"] += r.rowcount
                out["live_predictions"] += int(bool(r.rowcount and probs))
    return out
