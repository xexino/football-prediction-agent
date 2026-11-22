"""Write normalised provider records into the database.

Handles duplicates (same teams within ±36h in one competition), kickoff changes, postponements,
multi-source result verification and conflicts, and append-only odds snapshots.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .catalog import BY_CODE, COMPETITIONS
from .db import Competition, Fixture, MatchStats, OddsObservation, ResultObservation, log, session_scope
from .providers.footballdata_uk import MatchRecord
from .teamnames import TeamResolver
from .timeutil import utcnow

PRIMARY_SOURCES = {"football_data_uk", "intl_results"}  # authoritative for team naming
DUP_WINDOW = timedelta(hours=36)


def ensure_competitions() -> None:
    with session_scope() as s:
        existing = {c.code: c for c in s.scalars(select(Competition))}
        for c in COMPETITIONS:
            comp = existing.get(c["code"]) or Competition(code=c["code"])
            comp.name, comp.country, comp.region = c["name"], c["country"], c["region"]
            comp.kind, comp.priority, comp.sources = c.get("kind", "league"), c["priority"], c["sources"]
            s.add(comp)


def odds_hash(bookmaker: str, kind: str, m: dict) -> str:
    payload = json.dumps([bookmaker, kind, sorted((k, v) for k, v in m.items() if v is not None)])
    return hashlib.sha1(payload.encode()).hexdigest()


def validate(rec: MatchRecord) -> str | None:
    """Reject records that cannot be right (never 'repair' them by guessing)."""
    now = utcnow()
    if not rec.home or not rec.away or rec.home.strip().lower() == rec.away.strip().lower():
        return "missing or identical team names"
    if rec.kickoff_utc.year < 1990 or rec.kickoff_utc > now + timedelta(days=400):
        return "implausible kickoff date"
    if rec.status == "finished":
        for g in (rec.home_goals, rec.away_goals):
            if g is None or g < 0 or g > 20:
                return f"invalid final score {rec.home_goals}-{rec.away_goals}"
        if rec.kickoff_utc > now + timedelta(hours=1):
            return "result reported for a match that has not started"
        if rec.ht_home is not None and rec.ht_away is not None and (rec.ht_home > rec.home_goals or rec.ht_away > rec.away_goals):
            return "half-time score exceeds full-time score"
    return None


class Ingestor:
    def __init__(self, s: Session, source: str):
        self.s, self.source = s, source
        self.resolver = TeamResolver(s)
        self.comp_ids = {c.code: c.id for c in s.scalars(select(Competition))}
        self._fx_index: dict[int, dict] = {}
        self.stats = defaultdict(int)

    def _index(self, comp_id: int) -> dict:
        if comp_id not in self._fx_index:
            idx = defaultdict(list)
            for f in self.s.scalars(select(Fixture).where(Fixture.competition_id == comp_id)):
                idx[(f.home_team_id, f.away_team_id)].append(f)
            self._fx_index[comp_id] = idx
        return self._fx_index[comp_id]

    def _candidates(self, comp_id: int) -> list[int] | None:
        idx = self._index(comp_id)
        ids = {t for k in idx for t in k}
        return list(ids) if ids else None

    def add(self, rec: MatchRecord) -> Fixture | None:
        comp_id = self.comp_ids.get(rec.comp_code)
        if comp_id is None:
            return None
        problem = validate(rec)
        if problem:
            self.stats["invalid_records"] += 1
            if self.stats["invalid_records"] <= 5:
                log("WARNING", "ingest", f"{self.source}: rejected {rec.home} v {rec.away} {rec.kickoff_utc:%Y-%m-%d}: {problem}")
            return None
        primary = self.source in PRIMARY_SOURCES
        national = BY_CODE[rec.comp_code].get("kind") == "international"
        cands = None if primary else self._candidates(comp_id)
        if primary:
            h, hc = self.resolver.resolve(rec.home, self.source, rec.country, cands, is_national=national)
            a, ac = self.resolver.resolve(rec.away, self.source, rec.country, cands, is_national=national)
        else:
            h, hc = self.resolver.resolve(rec.home, self.source, rec.country, cands, create=False)
            a, ac = self.resolver.resolve(rec.away, self.source, rec.country, cands, create=False)
            # anchor matching: one team + kickoff identifies the fixture, so the other name is an alias
            if (h is None) != (a is None):
                known = h if h is not None else a
                hits = [f for (fh, fa), fl in self._index(comp_id).items() for f in fl
                        if (fh == known if h is not None else fa == known)
                        and abs(f.kickoff_utc - rec.kickoff_utc) <= DUP_WINDOW]
                if len(hits) == 1:
                    from .teamnames import normalize

                    other = hits[0].away_team_id if h is not None else hits[0].home_team_id
                    self.resolver._add_alias(normalize(rec.away if h is not None else rec.home), self.source, other, 0.85)
                    self.resolver._cache.pop((self.source, f"{rec.country}|{rec.away if h is not None else rec.home}"), None)
                    if h is None:
                        h, hc = other, 0.85
                    else:
                        a, ac = other, 0.85
            if h is None:
                h, hc = self.resolver.resolve(rec.home, self.source, rec.country, cands, is_national=national)
            if a is None:
                a, ac = self.resolver.resolve(rec.away, self.source, rec.country, cands, is_national=national)
        if h is None or a is None or h == a:
            self.stats["unresolved"] += 1
            return None
        idx = self._index(comp_id)
        fx = None
        for f in idx[(h, a)]:
            if abs(f.kickoff_utc - rec.kickoff_utc) <= DUP_WINDOW:
                fx = f
                break
        now = utcnow()
        if fx is None:
            fx = Fixture(competition_id=comp_id, season=rec.season, home_team_id=h, away_team_id=a,
                         kickoff_utc=rec.kickoff_utc, match_date=rec.kickoff_utc.strftime("%Y-%m-%d"),
                         neutral=rec.neutral, status="scheduled", first_seen_source=self.source,
                         external_ids={self.source: rec.external_id} if rec.external_id else {})
            self.s.add(fx)
            self.s.flush()
            idx[(h, a)].append(fx)
            self.stats["fixtures_new"] += 1
        else:
            self.stats["fixtures_dup"] += 1
            if rec.external_id and fx.external_ids.get(self.source) != rec.external_id:
                fx.external_ids = {**fx.external_ids, self.source: rec.external_id}
            if fx.status in ("scheduled", "postponed") and rec.kickoff_utc != fx.kickoff_utc and (primary or not fx.first_seen_source):
                if abs(rec.kickoff_utc - fx.kickoff_utc) > timedelta(minutes=1):
                    self.stats["kickoff_changes"] += 1
                    fx.kickoff_utc = rec.kickoff_utc
            if rec.season and not fx.season:
                fx.season = rec.season
        if min(hc, ac) < 0.95:
            self.stats["fuzzy_team_matches"] += 1

        # -------------------------------------------------- results / status
        if rec.status in ("finished", "postponed", "cancelled", "abandoned"):
            obs = dict(fixture_id=fx.id, source=self.source, status=rec.status, home_goals=rec.home_goals,
                       away_goals=rec.away_goals, ht_home_goals=rec.ht_home, ht_away_goals=rec.ht_away,
                       retrieved_at=rec.retrieved_at or now)
            r = self.s.execute(sqlite_insert(ResultObservation).values(**obs).on_conflict_do_nothing())
            if r.rowcount:
                self.stats["result_observations"] += 1
                reconcile(self.s, fx)
            fx.updated_at = now

        # -------------------------------------------------- stats
        if rec.stats:
            vals = dict(fixture_id=fx.id, source=self.source, retrieved_at=rec.retrieved_at or now, **rec.stats)
            self.s.execute(sqlite_insert(MatchStats).values(**vals).on_conflict_do_nothing())

        # -------------------------------------------------- odds (append-only snapshots)
        for bookmaker, kind, m in rec.odds:
            hsh = odds_hash(bookmaker, kind, m)
            vals = dict(fixture_id=fx.id, source=self.source, bookmaker=bookmaker, kind=kind,
                        retrieved_at=rec.retrieved_at or now, source_url=rec.source_url, is_current=True,
                        content_hash=hsh, **{k: m.get(k) for k in
                                             ("home", "draw", "away", "over25", "under25", "ah_line", "ah_home", "ah_away")})
            r = self.s.execute(sqlite_insert(OddsObservation).values(**vals).on_conflict_do_nothing())
            if r.rowcount:
                self.stats["odds_snapshots"] += 1
                if fx.status == "finished":
                    continue  # 'current' flag only matters for upcoming fixtures
                # older snapshots of the same book/kind are no longer current
                self.s.query(OddsObservation).filter(
                    OddsObservation.fixture_id == fx.id, OddsObservation.source == self.source,
                    OddsObservation.bookmaker == bookmaker, OddsObservation.kind == kind,
                    OddsObservation.content_hash != hsh, OddsObservation.is_current.is_(True),
                ).update({"is_current": False}, synchronize_session=False)
        return fx


def reconcile(s: Session, fx: Fixture) -> None:
    """Derive a fixture's verified status/result from all source observations.

    * all sources agreeing on a final score -> finished, verified
    * sources disagreeing -> result_conflict = True and the result is withheld (bets stay pending)
    * only postponed/cancelled/abandoned reports -> that status (no score)
    """
    obs = s.scalars(select(ResultObservation).where(ResultObservation.fixture_id == fx.id)
                    .order_by(ResultObservation.retrieved_at)).all()
    latest = {}
    for o in obs:
        latest[o.source] = o
    finals = {(o.home_goals, o.away_goals) for o in latest.values()
              if o.status == "finished" and o.home_goals is not None and o.away_goals is not None}
    if len(finals) == 1:
        o = next(o for o in latest.values() if o.status == "finished")
        fx.status, fx.home_goals, fx.away_goals = "finished", o.home_goals, o.away_goals
        hts = {(x.ht_home_goals, x.ht_away_goals) for x in latest.values() if x.ht_home_goals is not None}
        if len(hts) == 1:
            fx.ht_home_goals, fx.ht_away_goals = next(iter(hts))
        fx.result_source = ",".join(sorted(k for k, v in latest.items() if v.status == "finished"))
        fx.result_verified_at = utcnow()
        fx.result_conflict = False
    elif len(finals) > 1:
        if not fx.result_conflict:
            log("WARNING", "ingest", f"result conflict for fixture {fx.id}: {sorted(finals)} from {sorted(latest)}")
        fx.result_conflict = True
        fx.status, fx.home_goals, fx.away_goals = "unknown", None, None
    else:
        statuses = {o.status for o in latest.values()}
        for st in ("abandoned", "cancelled", "postponed"):
            if st in statuses and fx.status != "finished":
                fx.status = st
                break


def ingest_records(records: list[MatchRecord], source: str) -> dict:
    with session_scope() as s:
        ing = Ingestor(s, source)
        for rec in sorted(records, key=lambda r: r.kickoff_utc):
            ing.add(rec)
        return dict(ing.stats)


def merge_duplicates() -> int:
    """Merge fixtures created by a secondary source that duplicate a primary-source fixture
    (same competition, same slot for one team, kickoff within ±36h). Only fixtures without
    predictions, bets or odds are merged, so no audit record is touched."""
    from .db import Prediction, TeamAlias, VirtualBet
    from .teamnames import normalize

    merged = 0
    with session_scope() as s:
        dups = s.scalars(select(Fixture).where(Fixture.first_seen_source.not_in(PRIMARY_SOURCES))).all()
        for d in dups:
            if (s.scalar(select(Prediction.id).where(Prediction.fixture_id == d.id).limit(1)) or
                    s.scalar(select(VirtualBet.id).where(VirtualBet.fixture_id == d.id).limit(1)) or
                    s.scalar(select(OddsObservation.id).where(OddsObservation.fixture_id == d.id).limit(1))):
                continue
            cands = s.scalars(select(Fixture).where(
                Fixture.competition_id == d.competition_id, Fixture.id != d.id,
                Fixture.first_seen_source.in_(PRIMARY_SOURCES),
                Fixture.kickoff_utc.between(d.kickoff_utc - DUP_WINDOW, d.kickoff_utc + DUP_WINDOW),
                ((Fixture.home_team_id == d.home_team_id) | (Fixture.away_team_id == d.away_team_id)))).all()
            if len(cands) != 1:
                continue
            p = cands[0]
            for wrong, right in ((d.home_team_id, p.home_team_id), (d.away_team_id, p.away_team_id)):
                if wrong != right:
                    from .db import Team

                    t = s.get(Team, wrong)
                    with s.no_autoflush:
                        s.query(TeamAlias).filter(TeamAlias.team_id == wrong, TeamAlias.source == d.first_seen_source).delete()
                        exists = s.scalar(select(TeamAlias.id).where(TeamAlias.alias_norm == normalize(t.name),
                                                                     TeamAlias.source == d.first_seen_source,
                                                                     TeamAlias.team_id == right))
                    if not exists:
                        s.add(TeamAlias(alias_norm=normalize(t.name), source=d.first_seen_source, team_id=right, confidence=0.85))
            for o in s.scalars(select(ResultObservation).where(ResultObservation.fixture_id == d.id)).all():
                with s.no_autoflush:
                    same = s.scalar(select(ResultObservation.id).where(
                        ResultObservation.fixture_id == p.id, ResultObservation.source == o.source,
                        ResultObservation.status == o.status, ResultObservation.home_goals.is_(o.home_goals) if o.home_goals is None
                        else ResultObservation.home_goals == o.home_goals,
                        ResultObservation.away_goals.is_(o.away_goals) if o.away_goals is None
                        else ResultObservation.away_goals == o.away_goals))
                if same:
                    s.delete(o)  # identical report already attached to the real fixture
                else:
                    o.fixture_id = p.id
            p.external_ids = {**(p.external_ids or {}), **(d.external_ids or {})}
            s.flush()  # observations moved/removed before the fixture row goes
            s.delete(d)
            s.flush()
            reconcile(s, p)
            merged += 1
    if merged:
        log("INFO", "ingest", f"merged {merged} duplicate fixtures from secondary sources")
    return merged
