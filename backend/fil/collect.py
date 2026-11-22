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
from .providers.others import (APIFootball, FootballDataOrg, InternationalResults, ODDS_API_SPORTS, OddsAPI,
                               TheSportsDB)
from .timeutil import utcnow

PROVIDERS = {p.key: p for p in (FootballDataUK, TheSportsDB, InternationalResults, FootballDataOrg, OddsAPI, APIFootball)}


def provider(key: str):
    p = PROVIDERS[key]()
    p.register()
    return p


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
    for c in COMPETITIONS:
        if "tsdb" not in c["sources"]:
            continue
        try:
            recs = tsdb.league_events(c["code"])
            n += len(recs)
            ingest_records(recs, tsdb.key)
        except ProviderError as e:
            errs.append(f"{c['code']}: {e}")
    if errs and not n:
        tsdb.mark_error("; ".join(errs)[:900], requests=len(errs))
    else:
        tsdb.mark_success(records=n, requests=2 * sum(1 for c in COMPETITIONS if "tsdb" in c["sources"]))
    out["thesportsdb"] = {"records": n, "errors": errs}
    from .ingest import merge_duplicates

    out["merged_duplicates"] = merge_duplicates()

    fdorg = provider("football_data_org")
    if fdorg.configured:
        try:
            recs = fdorg.matches()
            out["football_data_org"] = ingest_records(recs, fdorg.key)
            fdorg.mark_success(records=len(recs), requests=1, quota=getattr(fdorg, "last_quota", None))
        except ProviderError as e:
            fdorg.mark_error(str(e), requests=1)
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
