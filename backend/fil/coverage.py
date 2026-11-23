"""Competition coverage & eligibility assessment. Never fills gaps with invented data:
a competition without enough real history and real odds is simply marked ineligible."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from .db import Competition, Fixture, MatchStats, OddsObservation, TeamNews, session_scope
from .timeutil import utcnow

MIN_HISTORY = 300


def assess_coverage(engine=None) -> list[dict]:
    now = utcnow()
    out = []
    with session_scope() as s:
        for c in s.scalars(select(Competition).order_by(Competition.priority, Competition.code)):
            base = select(func.count(Fixture.id)).where(Fixture.competition_id == c.id)
            hist = s.scalar(base.where(Fixture.status == "finished", Fixture.kickoff_utc > now - timedelta(days=1100)))
            season = s.scalar(base.where(Fixture.status == "finished", Fixture.kickoff_utc > now - timedelta(days=150)))
            upcoming_ids = s.scalars(select(Fixture.id).where(
                Fixture.competition_id == c.id, Fixture.status == "scheduled", Fixture.kickoff_utc > now,
                Fixture.kickoff_utc < now + timedelta(days=14))).all()
            with_odds = s.scalar(select(func.count(func.distinct(OddsObservation.fixture_id))).where(
                OddsObservation.fixture_id.in_(upcoming_ids), OddsObservation.kind == "pre_match")) if upcoming_ids else 0
            hist_odds = s.scalar(select(func.count(func.distinct(OddsObservation.fixture_id))).join(
                Fixture, Fixture.id == OddsObservation.fixture_id).where(
                Fixture.competition_id == c.id, Fixture.kickoff_utc > now - timedelta(days=400)))
            recent = s.scalar(base.where(Fixture.status == "finished", Fixture.kickoff_utc > now - timedelta(days=400)))
            stats = s.scalar(select(func.count(MatchStats.id)).join(Fixture, Fixture.id == MatchStats.fixture_id).where(
                Fixture.competition_id == c.id, Fixture.kickoff_utc > now - timedelta(days=400)))
            xg = s.scalar(select(func.count(MatchStats.id)).join(Fixture, Fixture.id == MatchStats.fixture_id).where(
                Fixture.competition_id == c.id, MatchStats.home_xg.is_not(None), Fixture.kickoff_utc > now - timedelta(days=150)))
            news = s.scalar(select(func.count(TeamNews.id)).join(Fixture, Fixture.id == TeamNews.fixture_id).where(Fixture.competition_id == c.id))
            model_ready = bool(engine and c.code in engine.dc)
            odds_share = (hist_odds / recent) if recent else 0.0
            stats_share = (stats / recent) if recent else 0.0
            completeness = round(100 * (0.35 * min(hist / MIN_HISTORY, 1) + 0.35 * odds_share + 0.2 * stats_share
                                        + 0.1 * (1 if news else 0)), 1)
            quality = round(min(100, completeness * (1.0 if model_ready else 0.6)), 1)
            reasons = []
            if hist < MIN_HISTORY:
                reasons.append(f"only {hist} historical matches available (need {MIN_HISTORY})")
            if odds_share < 0.5:
                reasons.append("no reliable odds history")
            if not model_ready and hist >= MIN_HISTORY:
                reasons.append("model not fitted (cup/international format or insufficient league data)")
            eligible = not reasons
            live_sources = [k for k in ("apif", "fdorg") if k in (c.sources or {})]
            from .config import settings as _st

            live_ready = ("apif" in live_sources and bool(_st.api_football_key)) or ("fdorg" in live_sources and bool(_st.football_data_org_key))
            if eligible and stats_share >= 0.5:
                status = "FULL COVERAGE"
            elif eligible:
                status = "PARTIAL COVERAGE"
            elif hist >= 50 or season >= 20:
                status = "FIXTURES AND RESULTS ONLY"
            elif live_ready:
                status = "LIVE SCORES ONLY"
            elif hist > 0 or len(upcoming_ids) > 0:
                status = "COVERAGE ONLY — NOT ENOUGH DATA FOR PREDICTIONS"
            else:
                status = "UNAVAILABLE"
            cov = {
                "coverage_status": status, "live": ("delayed score (football-data.org free)" if "fdorg" in live_sources and _st.football_data_org_key
                                                   else "awaiting API_FOOTBALL_KEY" if "apif" in live_sources else "no live source"),
                "historical_matches": hist, "current_season_matches": season, "upcoming_14d": len(upcoming_ids),
                "upcoming_with_odds": with_odds, "odds_history_share": round(odds_share, 3),
                "stats_share": round(stats_share, 3), "xg_current_season": xg, "team_news_items": news,
                "lineups": "not available from connected providers", "completeness": completeness,
                "quality_score": quality, "eligible": eligible, "reasons": reasons, "sources": c.sources,
            }
            c.coverage, c.eligible, c.coverage_updated_at = cov, eligible, now
            out.append({"code": c.code, "name": c.name, "region": c.region, **cov})
    return out
