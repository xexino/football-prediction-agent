"""Data-collection jobs: run every provider adapter and store what it returns.

A failing provider never stops the others; its error is recorded on the Data Sources page.
"""
from __future__ import annotations

from datetime import datetime, timedelta

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
    skipped_calls = False
    skipped = _skip_if_open(tsdb)
    for c in ([] if skipped else COMPETITIONS):
        if "tsdb" not in c["sources"]:
            continue
        try:
            recs = tsdb.league_events(c["code"])
            n += len(recs)
            ingest_records(recs, tsdb.key)
        except ProviderError as e:
            if "request skipped" in str(e):  # provider marked down / still locked out: not a new failure,
                skipped_calls = True          # never counted towards the 6 h circuit breaker
                break
            errs.append(f"{c['code']}: {e}")
    stale = getattr(tsdb, "stale_served", 0)  # read before mark_success resets it
    if skipped:
        out["thesportsdb"] = skipped
    elif errs and not n:
        tsdb.mark_error("; ".join(errs)[:900], requests=len(errs))
    else:
        tsdb.mark_success(records=n, requests=2 * sum(1 for c in COMPETITIONS if "tsdb" in c["sources"]))
    out.setdefault("thesportsdb", {"records": n, "errors": errs, "stale_cache": stale, "skipped_calls": skipped_calls})
    from .ingest import merge_duplicates

    out["merged_duplicates"] = merge_duplicates()

    out["football_data_org"] = collect_fdorg("quick")
    oapi = provider("the_odds_api")
    if oapi.configured:
        out["the_odds_api"] = collect_odds_api(oapi)
    return out



def collect_odds_api(oapi=None) -> dict:
    """The Odds API: one recorded outcome per run (council DP-3). Previously mark_success ran after mark_error and
    reset the failure count, so the circuit breaker could never open and outages showed as healthy."""
    oapi = oapi or provider("the_odds_api")
    n, errs, ok_calls = 0, [], 0
    for code in ODDS_API_SPORTS:
        try:
            recs = oapi.odds(code)
            n += len(recs)
            ok_calls += 1
            ingest_records(recs, oapi.key)
        except NotConfigured:
            break
        except ProviderError as e:
            errs.append(f"{code}: {e}")
    if errs:  # any failure counts (a partial 429 must not reset the circuit breaker / quota protection)
        oapi.mark_error(f"{len(errs)} of {len(errs) + ok_calls} requests failed: " + "; ".join(errs)[:850],
                        requests=len(errs) + ok_calls)
    else:
        oapi.mark_success(records=n, requests=ok_calls + len(errs), quota=getattr(oapi, "last_quota", None))
    return {"records": n, "errors": errs} if errs else {"records": n}

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
        # one snapshot per day: a re-run on the same day replaces that day's rows (earlier days are kept)
        s.query(StandingSnapshot).filter(StandingSnapshot.competition_id == comp.id, StandingSnapshot.season == season,
                                         StandingSnapshot.snapshot_date == ts.strftime("%Y-%m-%d"),
                                         StandingSnapshot.source == "football_data_org").delete()
        for r in rows:
            tid, _ = res.resolve(r["team"], "football_data_org", "", list(team_ids) or None, create=False)
            if tid is None and r.get("team_full"):
                tid, _ = res.resolve(r["team_full"], "football_data_org", "", list(team_ids) or None, create=False)
            vals = dict(competition_id=comp.id, season=season, snapshot_date=ts.strftime("%Y-%m-%d"), team_id=tid,
                        team_name=r["team"] + (f" ({r['group'].replace('_', ' ').title()})"
                                               if (r.get("group") or "").upper().startswith("GROUP") else ""),
                        position=r["position"],
                        played=r["played"], won=r["won"], draw=r["draw"], lost=r["lost"], goals_for=r["goals_for"],
                        goals_against=r["goals_against"], points=r["points"], form=r.get("form"),
                        source="football_data_org", retrieved_at=ts)
            n += s.execute(sqlite_insert(StandingSnapshot).values(**vals).on_conflict_do_nothing()).rowcount
    return n



# ----------------------------------------------------------------------------- overdue-results fallback
# Leagues whose only result source is football-data.co.uk, which publishes them 2-3 days late (council cycle
# 2026-11-26 00:50: the Engine A bet on Cremonese–Avellino stayed open for days). Deliberately NOT a catalog
# `tsdb` source: that would also switch on fixture discovery (more 429s, more chances of duplicate fixtures).
# ENG5 and JPN1 have no usable free fallback and stay on football-data.co.uk's timing.
OVERDUE_TSDB_LEAGUE = {"ITA2": "4394", "ENG3": "4396", "ENG4": "4397", "SCO1": "4330",
                       # UEFA club competitions (council cycle 2026-11-27 00:50): TheSportsDB is their only result source
                       # and its past-events list returns ~1 result per round, so 6 of 6 games of 26 Nov never resolved
                       "UEL": BY_CODE["UEL"]["sources"]["tsdb"], "UECL": BY_CODE["UECL"]["sources"]["tsdb"]}
OVERDUE_MAX_CALLS = 8  # day lists + per-fixture searches together, per run
DAY_LIST_TTL = 12 * 3600
SEARCH_TTL = 3 * 3600
OVERDUE_AFTER = timedelta(hours=3)
OVERDUE_LOOKBACK = timedelta(days=7)
FINAL_STATUSES = {"FT", "Match Finished"}  # explicit full time only: never a stuck live score, never HT/2H/AET/PST


# football-data.co.uk abbreviations vs TheSportsDB full names; used ONLY by the fallback matcher (changing
# teamnames.normalize would desynchronise the stored TeamAlias.alias_norm rows)
_EXPAND = {"weds": "wednesday", "rvs": "rovers", "peterboro": "peterborough", "wand": "wanderers"}


def names_match(a: str, b: str) -> bool:
    """Normalised names are equal, or the shorter one's words are the start or the end of the longer one's
    ("bradford" / "bradford city", "verona" / "hellas verona"). Only used together with the strict context
    below (same league id, same date, both teams, a single candidate), never to create an alias."""
    ta, tb = [_EXPAND.get(t, t) for t in a.split()], [_EXPAND.get(t, t) for t in b.split()]
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    short, long_ = sorted((ta, tb), key=len)
    if len(short) == len(long_) or len("".join(short)) < 4:
        return False
    return long_[:len(short)] == short or long_[-len(short):] == short


def overdue_events_to_results(events: list[dict], league_id: str, fixtures: list[dict]) -> list[tuple[int, int, int]]:
    """Pure matching step: (fixture_id, home_goals, away_goals) for events that are explicitly full time, belong
    to this league, and whose BOTH team names match the fixture's known names (canonical name or an alias
    already in the DB, normalised; see names_match). Nothing created. `fixtures`: dicts with id, date,
    home_names, away_names (sets of normalised names) — only the overdue fixtures of that league and date."""
    from .teamnames import normalize

    out = []
    for e in events:
        if str(e.get("idLeague") or "") != league_id or (e.get("strStatus") or "") not in FINAL_STATUSES:
            continue
        if (e.get("strPostponed") or "no").lower() == "yes":
            continue
        try:
            hg, ag = int(e.get("intHomeScore")), int(e.get("intAwayScore"))
        except (TypeError, ValueError):
            continue
        hn, an = normalize(e.get("strHomeTeam") or ""), normalize(e.get("strAwayTeam") or "")
        hits = [f for f in fixtures if f["date"] == (e.get("dateEvent") or "")
                and any(names_match(hn, x) for x in f["home_names"]) and any(names_match(an, x) for x in f["away_names"])]
        if len(hits) == 1 and 0 <= hg <= 20 and 0 <= ag <= 20:
            out.append((hits[0]["id"], hg, ag))
    # the other direction too: a fixture claimed by two events (e.g. a TheSportsDB duplicate) is dropped
    per_fixture: dict[int, int] = {}
    for fid, _, _ in out:
        per_fixture[fid] = per_fixture.get(fid, 0) + 1
    return [r for r in out if per_fixture[r[0]] == 1]


def collect_overdue_results(now: datetime | None = None) -> dict:
    """For fixtures >3 h past kick-off without a result: TheSportsDB's by-day list per (league, date), cached 12 h
    because the free key returns only ~3 events; then a per-fixture event search for the rest (open bets first,
    newest day first). At most OVERDUE_MAX_CALLS network requests per run, stopping at the first rate limit.
    Matches (see overdue_events_to_results) are recorded as `thesportsdb` result observations. Settlement then follows the normal rules.
    Known limit: a settled bet is final. If football-data.co.uk later reports a different score, reconcile marks
    a conflict and logs an ERROR; the bet is not reversed."""
    from .db import Competition, Fixture, ResultObservation, Team, TeamAlias, VirtualBet, session_scope
    from .ingest import reconcile
    from .teamnames import normalize
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    now = now or utcnow()
    with session_scope() as s:
        codes = {c.id: c.code for c in s.scalars(select(Competition).where(Competition.code.in_(list(OVERDUE_TSDB_LEAGUE))))}
        fx = s.scalars(select(Fixture).where(
            Fixture.competition_id.in_(list(codes) or [-1]), Fixture.status == "scheduled",
            Fixture.home_goals.is_(None), Fixture.kickoff_utc < now - OVERDUE_AFTER,
            Fixture.kickoff_utc > now - OVERDUE_LOOKBACK)).all()
        # never give a result to the leftover copy of a duplicated match (its twin, under other team ids, is already
        # finished): the match would count twice in both engines' history (council cycle 2026-11-27 00:50 skeptic)
        def _twin_finished(f) -> bool:
            return s.scalar(select(Fixture.id).where(
                Fixture.competition_id == f.competition_id, Fixture.id != f.id, Fixture.status == "finished",
                Fixture.kickoff_utc.between(f.kickoff_utc - timedelta(days=2), f.kickoff_utc + timedelta(days=2)),
                (Fixture.home_team_id == f.home_team_id) | (Fixture.away_team_id == f.away_team_id)
                | (Fixture.home_team_id == f.away_team_id) | (Fixture.away_team_id == f.home_team_id)).limit(1)) is not None

        fx = [f for f in fx if not _twin_finished(f)]
        bet_fx = set(s.scalars(select(VirtualBet.fixture_id).where(
            VirtualBet.fixture_id.in_([f.id for f in fx] or [-1]), VirtualBet.status == "pending")))
        team_ids = {t for f in fx for t in (f.home_team_id, f.away_team_id)}
        names: dict[int, set] = {t: set() for t in team_ids}
        canonical: dict[int, str] = {}
        for tid, name in s.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids or [-1]))):
            names[tid].add(normalize(name))
            canonical[tid] = name
        for tid, alias in s.execute(select(TeamAlias.team_id, TeamAlias.alias_norm).where(TeamAlias.team_id.in_(team_ids or [-1]))):
            names[tid].add(alias)
        by_pair: dict[tuple[str, str], list[dict]] = {}
        for f in fx:
            d = f.kickoff_utc.strftime("%Y-%m-%d")
            by_pair.setdefault((codes[f.competition_id], d), []).append(
                dict(id=f.id, date=d, home_names=names[f.home_team_id], away_names=names[f.away_team_id], bet=f.id in bet_fx,
                     home_query=canonical[f.home_team_id]))
    order = sorted(by_pair, key=lambda k: (not any(x["bet"] for x in by_pair[k]), [-ord(ch) for ch in k[1]], k[0]))
    out = {"overdue_fixtures": sum(len(v) for v in by_pair.values()), "pairs": len(order), "asked": 0,
           "results_found": 0, "errors": []}
    if not order:
        return out
    tsdb = provider("thesportsdb")
    skipped = _skip_if_open(tsdb)
    if skipped:
        return {**out, **skipped}
    stale0 = getattr(tsdb, "stale_served", 0)
    done: set[int] = set()

    def record(found: list[tuple[int, int, int]], ts) -> None:
        with session_scope() as s:
            for fid, hg, ag in found:
                if fid in done:
                    continue
                r = s.execute(sqlite_insert(ResultObservation).values(
                    fixture_id=fid, source=tsdb.key, status="finished", home_goals=hg, away_goals=ag,
                    retrieved_at=ts or utcnow()).on_conflict_do_nothing())
                done.add(fid)
                if r.rowcount:
                    out["results_found"] += 1
                    f = s.get(Fixture, fid)
                    reconcile(s, f)
                    f.updated_at = utcnow()
                    log("INFO", "collect", f"overdue result from TheSportsDB (single source until football-data.co.uk "
                                           f"publishes): fixture {fid} {hg}-{ag}")

    def ask(endpoint: str, params: dict, ttl: int):
        """One budgeted call; None = stop the whole fallback (rate limit / stale cache / budget spent)."""
        if out["asked"] + len(out["errors"]) >= OVERDUE_MAX_CALLS:
            return None
        try:
            events, url, ts = tsdb._events(endpoint, params, ttl=ttl)
        except ProviderError as e:
            skipped_req = "marked down" in str(e) or "request skipped" in str(e)
            out["skipped" if skipped_req else "errors"] = out.get("skipped" if skipped_req else "errors", []) + [f"{endpoint} {params}: {e}"]
            return None if ("429" in str(e) or skipped_req) else ([], None)
        if getattr(tsdb, "last_from_cache", False):
            out["cached"] = out.get("cached", 0) + 1  # a fresh cached answer costs no request
        else:
            out["asked"] += 1
        if getattr(tsdb, "stale_served", 0) > stale0:  # an old cached answer is not a result
            out["stale_cache"] = tsdb.stale_served - stale0
            return None
        return events, ts

    def search(code: str, day: str, fx: dict) -> bool:
        res = ask("searchevents.php", {"e": fx["home_query"].replace(" ", "_"), "d": day}, SEARCH_TTL)
        if res is None:
            return False
        record(overdue_events_to_results(res[0], OVERDUE_TSDB_LEAGUE[code], [fx]), res[1])
        return True

    def day_ttl(day: str) -> int:
        # a day's list is cached 12 h only once every match of that day is surely over (the free key returns
        # only ~3 events, the same ones every time); otherwise 2 h
        end = datetime.fromisoformat(day) + timedelta(days=1)
        return DAY_LIST_TTL if now > end + OVERDUE_AFTER else 2 * 3600

    items = [(code, day, fx) for code, day in order for fx in by_pair[(code, day)]]
    newest = lambda t: [-ord(ch) for ch in t[1]]  # noqa: E731
    ok = True
    # 1) open-bet fixtures: a direct search first (the capped day list may never contain them)
    for code, day, fx in sorted((t for t in items if t[2]["bet"]), key=newest):
        if not (ok := search(code, day, fx)):
            break
    # 2) one by-day list per (league, date)
    for code, day in (order if ok else []):
        if all(f["id"] in done for f in by_pair[(code, day)]):
            continue
        res = ask("eventsday.php", {"d": day, "l": OVERDUE_TSDB_LEAGUE[code]}, day_ttl(day))
        if res is None:
            ok = False
            break
        record(overdue_events_to_results(res[0], OVERDUE_TSDB_LEAGUE[code], by_pair[(code, day)]), res[1])
    # 3) per-fixture search for what the capped lists did not contain, newest day first
    for code, day, fx in (sorted((t for t in items if t[2]["id"] not in done and not t[2]["bet"]), key=newest) if ok else []):
        if not search(code, day, fx):
            break
    if out["errors"] and not out["asked"]:
        tsdb.mark_error("; ".join(out["errors"])[:900], requests=len(out["errors"]))
    out["still_overdue"] = out["overdue_fixtures"] - len(done)
    return out
