"""Data-collection jobs: run every provider adapter and store what it returns.

A failing provider never stops the others; its error is recorded on the Data Sources page.
"""
from __future__ import annotations

from .catalog import BY_CODE, COMPETITIONS, FD_UK_DIV, FD_UK_NEW
from .config import settings
from .db import log
from .ingest import ensure_competitions, ingest_records
from .providers.base import NotConfigured, ProviderError
from .providers.footballdata_uk import FootballDataUK, season_codes
from .providers.football_data_org import AuthError, FootballDataOrg, Restricted
from .providers.others import APIFootball, InternationalResults, ODDS_API_SPORTS, OddsAPI, TheSportsDB
from .timeutil import utcnow

PROVIDERS = {p.key: p for p in (FootballDataUK, TheSportsDB, InternationalResults, FootballDataOrg, OddsAPI, APIFootball)}


def provider(key: str):
    p = PROVIDERS[key]()
    p.register()
    return p


def _skip_if_open(p) -> dict | None:
    if p.circuit_open():
        log("WARNING", "collect", f"{p.name}: circuit open after repeated failures — skipped until cooldown ends")
        return {"skipped": "circuit open"}
    return None


def register_all() -> None:
    ensure_competitions()
    for k in PROVIDERS:
        provider(k)


def collect_history(full: bool = False) -> dict:
    """Import historical + current-season results/odds/stats from football-data.co.uk.

    full=True loads all configured seasons; otherwise only the current season (refreshed results).
    """
    p = provider("football_data_uk")
    seasons = season_codes(settings.history_seasons) if full else season_codes(1)
    summary, errors, n_req, n_rec = {}, [], 0, 0
    for div, code in FD_UK_DIV.items():
        for season in seasons:
            try:
                ttl = 30 * 24 * 3600 if season != seasons[-1] else 3 * 3600
                recs = p.main_league_results(div, season, ttl=ttl)
                n_req += 1
                n_rec += len(recs)
                st = ingest_records(recs, p.key)
                summary[f"{code}:{season}"] = len(recs)
            except ProviderError as e:
                errors.append(f"{div}/{season}: {e}")
    since = utcnow().year - (settings.history_seasons if full else 1)
    for c3, code in FD_UK_NEW.items():
        try:
            recs = p.extra_league_results(c3, since, ttl=3 * 3600)
            n_req += 1
            n_rec += len(recs)
            ingest_records(recs, p.key)
            summary[code] = len(recs)
        except ProviderError as e:
            errors.append(f"{c3}: {e}")
    if errors and not n_rec:
        p.mark_error("; ".join(errors)[:900], requests=n_req)
    else:
        p.mark_success(records=n_rec, requests=n_req)
        if errors:
            log("WARNING", "collect", f"football-data.co.uk partial errors: {'; '.join(errors)[:900]}")
    return {"files": len(summary), "records": n_rec, "errors": errors}


def collect_fixtures() -> dict:
    """Discover upcoming fixtures + current odds from every available source."""
    out = {}
    p = provider("football_data_uk")
    try:
        recs = p.upcoming_fixtures()
        out["football_data_uk"] = ingest_records(recs, p.key)
        p.mark_success(records=len(recs), requests=2)
    except ProviderError as e:
        p.mark_error(f"fixtures: {e}", requests=2)
        out["football_data_uk"] = {"error": str(e)}

    tsdb = provider("thesportsdb")
    n, errs = 0, []
    skipped = _skip_if_open(tsdb)
    for c in ([] if skipped else COMPETITIONS):
        if "tsdb" not in c["sources"]:
            continue
        try:
            recs = tsdb.league_events(c["code"])
            n += len(recs)
            ingest_records(recs, tsdb.key)
        except ProviderError as e:
            errs.append(f"{c['code']}: {e}")
    if skipped:
        out["thesportsdb"] = skipped
    elif errs and not n:
        tsdb.mark_error("; ".join(errs)[:900], requests=len(errs))
    else:
        tsdb.mark_success(records=n, requests=2 * sum(1 for c in COMPETITIONS if "tsdb" in c["sources"]))
    out.setdefault("thesportsdb", {"records": n, "errors": errs})
    from .ingest import merge_duplicates

    out["merged_duplicates"] = merge_duplicates()

    out["football_data_org"] = collect_fdorg("quick")
    oapi = provider("the_odds_api")
    if oapi.configured:
        n = 0
        for code in ODDS_API_SPORTS:
            try:
                recs = oapi.odds(code)
                n += len(recs)
                ingest_records(recs, oapi.key)
            except NotConfigured:
                break
            except ProviderError as e:
                oapi.mark_error(f"{code}: {e}", requests=1)
        oapi.mark_success(records=n, requests=len(ODDS_API_SPORTS), quota=getattr(oapi, "last_quota", None))
        out["the_odds_api"] = {"records": n}
    return out


def collect_international() -> dict:
    p = provider("intl_results")
    try:
        recs = p.results(since_year=utcnow().year - 10)
        st = ingest_records(recs, p.key)
        p.mark_success(records=len(recs), requests=1)
        return {"records": len(recs), **st}
    except ProviderError as e:
        p.mark_error(str(e), requests=1)
        return {"error": str(e)}


def collect_results() -> dict:
    """Refresh current-season results (used for settlement) from every source."""
    out = {"football_data_uk": collect_history(full=False)}
    out["fixtures"] = collect_fixtures()  # TheSportsDB / football-data.org also report results
    return out


def collect_fdorg(mode: str = "quick") -> dict:
    """Synchronise football-data.org.

    quick    : one /matches request (±window) — fixtures, kickoff changes, results (every 3h)
    full     : competitions + current-season matches + standings for every plan competition (daily, ~25 requests)
    backfill : seasons 2023-2025 of competitions with no other history source (Champions League), once each
    """
    from datetime import timedelta as _td

    from .db import Competition, DataSource, StandingSnapshot, Team, session_scope
    from .providers.football_data_org import CUP_CODES, FREE_SEASONS, LEAGUE_CODES
    from .teamnames import TeamResolver
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    p = provider("football_data_org")
    if not p.configured:
        return {"skipped": "not configured (FOOTBALL_DATA_ORG_KEY not set)"}
    if (skipped := _skip_if_open(p)):
        return skipped
    out = {"mode": mode, "records": 0, "errors": [], "restricted": []}
    stats_total: dict = {}

    def ingest(recs):
        st = ingest_records(recs, p.key)
        out["records"] += len(recs)
        for k, v in st.items():
            stats_total[k] = stats_total.get(k, 0) + v

    try:
        if mode == "quick":
            ingest(p.matches(days_back=3, days_forward=7))
            out["in_play_seen_delayed"] = getattr(p, "in_play_seen", 0)
        elif mode == "full":
            comps = p.competitions()
            out["competitions"] = [c["code"] for c in comps if c.get("plan") == "TIER_ONE"]
            for code in [c for c in LEAGUE_CODES + CUP_CODES if c in out["competitions"] or not out["competitions"]]:
                try:
                    ingest(p.competition_matches(code, ttl=3 * 3600))
                except Restricted as e:
                    out["restricted"].append(str(e))
                if code in LEAGUE_CODES or code == "CL":
                    try:
                        rows, season, url, ts = p.standings(code)
                        out.setdefault("standings", {})[code] = _store_standings(code, rows, season, ts)
                    except Restricted as e:
                        out["restricted"].append(str(e))
        elif mode == "backfill":
            with session_scope() as s:
                ds = s.query(DataSource).filter_by(key=p.key).one()
                done = set((ds.quota_info or {}).get("backfilled", []))
            for code in CUP_CODES[:1]:  # Champions League: no other free history source
                for season in FREE_SEASONS[:-1]:
                    tag = f"{code}:{season}"
                    if tag in done:
                        continue
                    try:
                        ingest(p.competition_matches(code, season, ttl=30 * 24 * 3600))
                        done.add(tag)
                    except Restricted as e:
                        out["restricted"].append(str(e))
            out["backfilled"] = sorted(done)
    except AuthError as e:
        p.mark_error(str(e), requests=p.requests)
        out["errors"].append(str(e))
        return out
    except ProviderError as e:
        out["errors"].append(str(e))
    quota = p.quota() | {"last_sync": utcnow().isoformat(), "last_sync_mode": mode,
                         "scores": "delayed on the free plan — never displayed as live"}
    if mode == "backfill":
        quota["backfilled"] = out.get("backfilled", [])
    if out["errors"] and not out["records"]:
        p.mark_error("; ".join(out["errors"])[:900], requests=p.requests)
    else:
        p.mark_success(records=out["records"], requests=p.requests, quota=quota)
    out["ingest"] = stats_total
    out["requests"] = p.requests
    return out


def _store_standings(fd_code: str, rows: list[dict], season: str, ts) -> int:
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from .db import Competition, Fixture, StandingSnapshot, session_scope
    from .providers.football_data_org import FootballDataOrg
    from .teamnames import TeamResolver

    comp_code = FootballDataOrg().code_map().get(fd_code)
    n = 0
    with session_scope() as s:
        comp = s.scalars(select(Competition).where(Competition.code == comp_code)).first()
        if comp is None:
            return 0
        team_ids = {t for pair in s.execute(select(Fixture.home_team_id, Fixture.away_team_id)
                                             .where(Fixture.competition_id == comp.id)).all() for t in pair}
        res = TeamResolver(s)
        for r in rows:
            tid, _ = res.resolve(r["team"], "football_data_org", "", list(team_ids) or None, create=False)
            if tid is None and r.get("team_full"):
                tid, _ = res.resolve(r["team_full"], "football_data_org", "", list(team_ids) or None, create=False)
            vals = dict(competition_id=comp.id, season=season, snapshot_date=ts.strftime("%Y-%m-%d"), team_id=tid,
                        team_name=r["team"] + (f" ({r['group']})" if r.get("group") else ""), position=r["position"],
                        played=r["played"], won=r["won"], draw=r["draw"], lost=r["lost"], goals_for=r["goals_for"],
                        goals_against=r["goals_against"], points=r["points"], form=r.get("form"),
                        source="football_data_org", retrieved_at=ts)
            n += s.execute(sqlite_insert(StandingSnapshot).values(**vals).on_conflict_do_nothing()).rowcount
    return n
