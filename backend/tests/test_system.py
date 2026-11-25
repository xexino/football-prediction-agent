"""Database, ingestion, betting, pipeline, scheduler and API tests (synthetic data, offline)."""
from datetime import datetime, timedelta

import pytest

from fil.config import settings as _cfg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from fil.db import (BankrollTransaction, Fixture, OddsObservation, Prediction, ResultObservation, Team, ValueAssessment,
                    VirtualBet, session_scope)
from fil.ingest import ingest_records
from fil.providers.footballdata_uk import MatchRecord
from fil.timeutil import local_to_utc, utcnow
from tests.conftest import synthetic_league

IMMUTABLE_ERR = (IntegrityError, OperationalError)


def after_kickoff(monkeypatch, ko, hours=3):
    """Simulate the clock moving past kickoff (results may only be ingested for started matches)."""
    import fil.ingest

    monkeypatch.setattr(fil.ingest, "utcnow", lambda: ko + timedelta(hours=hours))


def rec(home="Alpha", away="Beta", ko=None, status="scheduled", hg=None, ag=None, odds=None, comp="ENG1"):
    return MatchRecord(comp_code=comp, season="2026/27", home=home, away=away, kickoff_utc=ko or (utcnow() + timedelta(days=2)),
                       country="England", status=status, home_goals=hg, away_goals=ag, odds=odds or [],
                       retrieved_at=utcnow(), source_url="test://")


# ------------------------------------------------------------------ time handling
def test_uk_time_to_utc():
    assert local_to_utc("15/07/2026", "15:00") == datetime(2026, 7, 15, 14, 0)  # BST
    assert local_to_utc("15/01/2026", "15:00") == datetime(2026, 1, 15, 15, 0)  # GMT
    assert local_to_utc("15/01/26", "") == datetime(2026, 1, 15, 15, 0)


# ------------------------------------------------------------------ ingestion
def test_duplicate_fixtures_are_merged(db):
    ko = utcnow() + timedelta(days=2)
    ingest_records([rec(ko=ko)], "football_data_uk")
    ingest_records([rec(ko=ko + timedelta(hours=2))], "football_data_uk")  # same match, kickoff moved
    with session_scope() as s:
        fx = s.scalars(select(Fixture)).all()
        assert len(fx) == 1
        assert fx[0].kickoff_utc == ko + timedelta(hours=2)


def test_team_name_resolution_across_sources(db):
    ko = utcnow() + timedelta(days=2)
    ingest_records([rec("Man United", "Nott'm Forest", ko)], "football_data_uk")
    ingest_records([rec("Manchester United", "Nottingham Forest", ko, status="finished", hg=2, ag=0)], "thesportsdb")
    with session_scope() as s:
        assert len(s.scalars(select(Fixture)).all()) == 1
        assert len(s.scalars(select(Team)).all()) == 2


def test_conflicting_results_flagged_and_withheld(db):
    ko = utcnow() - timedelta(days=1)
    ingest_records([rec(ko=ko, status="finished", hg=1, ag=0)], "football_data_uk")
    with session_scope() as s:
        f = s.scalars(select(Fixture)).one()
        assert (f.status, f.home_goals, f.result_conflict) == ("finished", 1, False)
    ingest_records([rec(ko=ko, status="finished", hg=2, ag=0)], "thesportsdb")
    with session_scope() as s:
        f = s.scalars(select(Fixture)).one()
        assert f.result_conflict and f.status == "unknown" and f.home_goals is None
        assert len(s.scalars(select(ResultObservation)).all()) == 2


def test_agreeing_sources_verify_result(db):
    ko = utcnow() - timedelta(days=1)
    ingest_records([rec(ko=ko, status="finished", hg=1, ag=1)], "football_data_uk")
    ingest_records([rec(ko=ko, status="finished", hg=1, ag=1)], "thesportsdb")
    with session_scope() as s:
        f = s.scalars(select(Fixture)).one()
        assert f.status == "finished" and not f.result_conflict
        assert f.result_source == "football_data_uk,thesportsdb"


def test_postponed_status(db):
    ingest_records([rec()], "football_data_uk")
    ingest_records([rec(status="postponed")], "thesportsdb")
    with session_scope() as s:
        assert s.scalars(select(Fixture)).one().status == "postponed"


def test_odds_snapshots_append_only(db):
    o1 = [("B365", "pre_match", {"home": 2.0, "draw": 3.4, "away": 3.8})]
    o2 = [("B365", "pre_match", {"home": 1.9, "draw": 3.5, "away": 4.0})]
    ingest_records([rec(odds=o1)], "football_data_uk")
    ingest_records([rec(odds=o1)], "football_data_uk")  # identical snapshot ignored
    ingest_records([rec(odds=o2)], "football_data_uk")
    with session_scope() as s:
        rows = s.scalars(select(OddsObservation).order_by(OddsObservation.id)).all()
        assert len(rows) == 2
        assert [r.is_current for r in rows] == [False, True]
        rows[0].home = 9.9
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()


def test_missing_odds_handled(db):
    ingest_records([rec(odds=[])], "football_data_uk")
    with session_scope() as s:
        assert s.scalars(select(OddsObservation)).all() == []


# ------------------------------------------------------------------ pipeline + betting
def _league_with_upcoming(db, upcoming_odds=None):
    recs, _, _ = synthetic_league(n_teams=16, seasons=3, end=utcnow() - timedelta(days=3))
    ingest_records(recs, "football_data_uk")
    ko = utcnow() + timedelta(days=1)
    ingest_records([rec("Team 0", "Team 1", ko, odds=upcoming_odds if upcoming_odds is not None else [
        ("B365", "pre_match", {"home": 2.1, "draw": 3.4, "away": 3.5, "over25": 1.9, "under25": 1.95}),
        ("BFE", "pre_match", {"home": 2.2, "draw": 3.5, "away": 3.7, "over25": 1.98, "under25": 2.02}),
        ("Avg", "pre_match", {"home": 2.05, "draw": 3.3, "away": 3.4, "over25": 1.86, "under25": 1.9})])],
        "football_data_uk")
    with session_scope() as s:
        return s.scalars(select(Fixture).where(Fixture.status == "scheduled")).one().id


def test_pipeline_produces_valid_predictions(db):
    from fil import pipeline

    fid = _league_with_upcoming(db)
    out = pipeline.predict_upcoming(pipeline.get_engine(force=True))
    assert out["predicted"] == 1
    with session_scope() as s:
        p = s.scalars(select(Prediction).where(Prediction.fixture_id == fid)).one()
        assert abs(sum(p.probs["1X2"].values()) - 1) < 1e-6
        assert abs(p.probs["OU25"]["over"] + p.probs["OU25"]["under"] - 1) < 1e-6
        assert 0 <= p.data_quality <= 100 and 0 <= p.confidence <= 100
        assert p.decision in ("BET", "NO_BET")
        assert p.quality_breakdown["team_news"] == 0
        if p.decision == "NO_BET":
            assert "NO BET" in p.explanation
        assert len(s.scalars(select(ValueAssessment).where(ValueAssessment.prediction_id == p.id)).all()) >= 5
    # second run with unchanged inputs: no new prediction rows
    out2 = pipeline.predict_upcoming(pipeline.get_engine())
    assert out2["unchanged"] == 1 and out2["predicted"] == 0


def test_prediction_immutable(db):
    from fil import pipeline

    _league_with_upcoming(db)
    pipeline.predict_upcoming(pipeline.get_engine(force=True))
    with session_scope() as s:
        p = s.scalars(select(Prediction)).first()
        p.probs = {"1X2": {"home": 1, "draw": 0, "away": 0}}
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()
    with session_scope() as s:
        p = s.scalars(select(Prediction)).first()
        s.delete(p)
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()


def test_no_odds_means_no_bet(db):
    from fil import pipeline

    _league_with_upcoming(db, upcoming_odds=[])
    pipeline.predict_upcoming(pipeline.get_engine(force=True))
    with session_scope() as s:
        p = s.scalars(select(Prediction)).one()
        assert p.decision == "NO_BET"
        assert s.scalars(select(VirtualBet)).all() == []


def _force_bet(db, price=2.6):
    """Create a qualifying bet directly through the betting engine."""
    from fil import pipeline
    from fil.betting import ensure_bankroll, place_bet

    fid = _league_with_upcoming(db)
    pipeline.predict_upcoming(pipeline.get_engine(force=True))
    with session_scope() as s:
        ensure_bankroll(s)
        p = s.scalars(select(Prediction)).first()
        fx = s.get(Fixture, fid)
        vas = s.scalars(select(ValueAssessment).where(ValueAssessment.prediction_id == p.id,
                                                      ValueAssessment.market == "1X2")).all()
        bets = [place_bet(s, prediction=p, assessment_row=va, fixture=fx, model_version_id=p.model_version_id) for va in vas]
        return fid, [b.id for b in bets if b]


def test_bankroll_and_risk_rules(db):
    fid, ids = _force_bet(db)
    with session_scope() as s:
        bets = s.scalars(select(VirtualBet)).all()
        assert 1 <= len(bets) <= 3
        assert all(b.stake == _cfg.risk.stake for b in bets)
        txs = s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.id)).all()
        assert txs[0].tx_type == "initial" and txs[0].amount == _cfg.risk.initial_bankroll
        assert txs[-1].balance_after == _cfg.risk.initial_bankroll - _cfg.risk.stake * len(bets)


def test_max_three_bets_per_match(db):
    from fil.betting import place_bet

    fid, ids = _force_bet(db)
    with session_scope() as s:
        p = s.scalars(select(Prediction)).first()
        fx = s.get(Fixture, fid)
        extra = s.scalars(select(ValueAssessment).where(ValueAssessment.prediction_id == p.id,
                                                        ValueAssessment.market == "OU25")).first()
        n_before = len(s.scalars(select(VirtualBet)).all())
        b = place_bet(s, prediction=p, assessment_row=extra, fixture=fx, model_version_id=p.model_version_id)
        assert (b is None) == (n_before >= 3)


def test_bet_after_kickoff_rejected_by_db(db):
    fid, ids = _force_bet(db)
    with session_scope() as s:
        b = s.get(VirtualBet, ids[0])
        nb = VirtualBet(prediction_id=b.prediction_id, value_assessment_id=b.value_assessment_id + 1000,
                        fixture_id=b.fixture_id, model_version_id=b.model_version_id, market="1X2", selection="home",
                        price=2.0, bookmaker="B365", stake=1, potential_return=2, model_prob=0.5, ev=0.0,
                        created_at=b.kickoff_utc + timedelta(minutes=1), kickoff_utc=b.kickoff_utc)
        s.add(nb)
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()


def test_settlement_and_no_resettle(db, monkeypatch):
    from fil.betting import settle_pending

    fid, ids = _force_bet(db)
    with session_scope() as s:
        fx = s.get(Fixture, fid)
        ko = fx.kickoff_utc
    assert settle_pending()["settled"] == 0  # no result yet -> stays pending
    after_kickoff(monkeypatch, ko)
    ingest_records([rec("Team 0", "Team 1", ko, status="finished", hg=2, ag=1)], "football_data_uk")
    out = settle_pending()
    assert out["settled"] == len(ids)
    with session_scope() as s:
        bets = s.scalars(select(VirtualBet)).all()
        home = [b for b in bets if b.selection == "home"]
        for b in bets:
            assert b.status in ("won", "lost")
            assert b.status == ("won" if b.selection == "home" else "lost")
        bal = s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.id.desc())).first().balance_after
        assert bal == pytest.approx(_cfg.risk.initial_bankroll - _cfg.risk.stake * len(bets) + _cfg.risk.stake * sum(b.price for b in home), abs=0.011 * _cfg.risk.stake)
        b = bets[0]
        b.status = "void"
        with pytest.raises(IMMUTABLE_ERR):
            s.flush()
        s.rollback()


def test_conflict_keeps_bet_pending(db, monkeypatch):
    from fil.betting import settle_pending

    fid, ids = _force_bet(db)
    with session_scope() as s:
        ko = s.get(Fixture, fid).kickoff_utc
    after_kickoff(monkeypatch, ko)
    ingest_records([rec("Team 0", "Team 1", ko, status="finished", hg=2, ag=1)], "football_data_uk")
    ingest_records([rec("Team 0", "Team 1", ko, status="finished", hg=1, ag=1)], "thesportsdb")
    out = settle_pending()
    assert out["settled"] == 0 and out["conflicts"] == len(ids)


def test_postponed_bet_voided_after_48h(db, monkeypatch):
    from fil import betting

    fid, ids = _force_bet(db)
    with session_scope() as s:
        ko = s.get(Fixture, fid).kickoff_utc
    ingest_records([rec("Team 0", "Team 1", ko, status="postponed")], "thesportsdb")
    assert betting.settle_pending()["voided"] == 0  # not yet 48h
    monkeypatch.setattr(betting, "utcnow", lambda: ko + timedelta(hours=49))
    assert betting.settle_pending()["voided"] == len(ids)
    with session_scope() as s:
        assert {b.status for b in s.scalars(select(VirtualBet))} == {"void"}
        assert s.scalars(select(BankrollTransaction).order_by(BankrollTransaction.id.desc())).first().balance_after == _cfg.risk.initial_bankroll


def test_select_bets_avoids_correlation():
    from fil.value import Assessment, select_bets

    mk = lambda m, s, ev: Assessment(m, s, None, 2.0, "B365", 1, 0.5, 0.5, 0.55, 0.52, 0.04, 0.1, ev)
    chosen = select_bets([mk("1X2", "home", 0.05), mk("AH", "home", 0.06), mk("OU25", "over", 0.03), mk("1X2", "away", 0.04)], [], 3)
    markets = [a.market for a in chosen]
    assert markets == ["AH", "OU25"]  # 1X2 dropped: correlated with AH; one per market


# ------------------------------------------------------------------ jobs / scheduler / backup / API
def test_job_runner_records_success_and_error(db, monkeypatch):
    from fil import jobs
    from fil.db import JobRun

    monkeypatch.setitem(jobs.JOBS, "ok", lambda: [("a", lambda: {"x": 1}, True)])
    monkeypatch.setitem(jobs.JOBS, "bad", lambda: [("a", lambda: 1 / 0, True)])
    assert jobs.run_job("ok")["status"] == "success"
    assert jobs.run_job("bad")["status"] == "error"
    with session_scope() as s:
        runs = {r.job: r for r in s.scalars(select(JobRun))}
        assert runs["ok"].status == "success" and runs["bad"].status == "error"
        assert "ZeroDivisionError" in runs["bad"].error
        assert runs["ok"].summary["steps"]["a"]["status"] == "success"


def test_failed_step_does_not_stop_others(db, monkeypatch):
    """Regression: a provider/merge crash used to abort settlement and predictions."""
    from fil import jobs

    ran = []
    monkeypatch.setitem(jobs.JOBS, "mixed", lambda: [
        ("collect", lambda: 1 / 0, False), ("settle", lambda: ran.append("settle") or {}, True),
        ("predict", lambda: ran.append("predict") or {}, True)])
    res = jobs.run_job("mixed")
    assert ran == ["settle", "predict"]
    assert res["status"] == "partial"
    assert res["summary"]["report"]["failed_steps"] == ["collect"]
    monkeypatch.setitem(jobs.JOBS, "crit", lambda: [("settle", lambda: 1 / 0, True), ("x", lambda: {}, False)])
    assert jobs.run_job("crit")["status"] == "error"


def test_job_lock_prevents_overlap(db, monkeypatch):
    from fil import jobs

    monkeypatch.setitem(jobs.JOBS, "ok", lambda: [("a", lambda: {}, False)])
    jobs._LOCK.acquire()
    try:
        assert jobs.run_job("ok")["status"] == "skipped"
    finally:
        jobs._LOCK.release()


def test_db_lease_prevents_cross_process_overlap(db, monkeypatch):
    from fil import jobs
    from fil.db import JobRun

    monkeypatch.setitem(jobs.JOBS, "ok", lambda: [("a", lambda: {}, False)])
    with session_scope() as s:
        s.add(JobRun(job="daily", status="running"))  # another process holds the lease
    assert jobs.run_job("ok")["status"] == "skipped"


def test_scheduler_starts_and_lists_jobs(db, monkeypatch):
    from fil import scheduler

    monkeypatch.setattr(scheduler, "_catch_up", lambda: None)
    scheduler.start()
    try:
        assert scheduler.running()
        st = scheduler.status()
        assert {j["job"] for j in st} == set(scheduler.SCHEDULE)
        assert all(j["next_run"] for j in st)
    finally:
        scheduler.shutdown()


def test_backup_and_restore(db, tmp_path):
    from fil.backup import backup, restore

    ingest_records([rec()], "football_data_uk")
    f = backup(tmp_path / "bk", verify=True)
    assert f.exists() and f.suffix == ".gz"
    restore(f)
    from fil.integrity import check_database
    chk = check_database()
    assert chk["ok"] and chk["counts"]["fixtures"] == 1  # restored data is really there


def test_api_endpoints(db):
    from fastapi.testclient import TestClient

    from fil import pipeline
    from fil.api import app

    _league_with_upcoming(db)
    pipeline.predict_upcoming(pipeline.get_engine(force=True))
    with TestClient(app) as c:
        for ep in ("health", "overview", "upcoming", "predictions", "bets", "analytics", "sources", "system", "reports", "meta"):
            r = c.get(f"/api/{ep}")
            assert r.status_code == 200, ep
        assert c.get("/api/health").json()["simulation_only"] is True
        ov = c.get("/api/overview").json()
        assert ov["bankroll"]["starting_bankroll"] == _cfg.risk.initial_bankroll
        up = c.get("/api/upcoming").json()["fixtures"]
        assert up and "prediction" in up[0]
        pid = c.get("/api/predictions").json()["items"][0]["id"]
        assert c.get(f"/api/predictions/{pid}").status_code == 200
        assert c.post("/api/admin/run/daily").status_code == 403  # admin disabled without token
        from fil.config import settings
        settings.admin_token = "s3cret"
        try:
            assert c.post("/api/admin/run/daily", headers={"X-Admin-Token": "wrong"}).status_code == 401
            assert c.post("/api/admin/run/nope", headers={"X-Admin-Token": "s3cret"}).status_code == 404
        finally:
            settings.admin_token = ""


def test_anchor_matching_merges_unrecognised_name(db):
    ko = utcnow() - timedelta(days=2)
    ingest_records([rec("Getafe", "Ath Madrid", ko)], "football_data_uk")
    ingest_records([rec("Getafe", "Atlético Madrid", ko, status="finished", hg=0, ag=1)], "thesportsdb")
    with session_scope() as s:
        fx = s.scalars(select(Fixture)).all()
        assert len(fx) == 1 and fx[0].home_goals == 0 and fx[0].away_goals == 1


def test_merge_duplicates_cleans_existing(db):
    from fil.ingest import merge_duplicates

    ko = utcnow() + timedelta(days=2)
    ingest_records([rec("Getafe", "Ath Madrid", ko)], "football_data_uk")
    # simulate a legacy duplicate created before anchor matching existed
    with session_scope() as s:
        from fil.db import Competition
        comp = s.scalars(select(Competition).where(Competition.code == "ENG1")).one()
        getafe = s.scalars(select(Team).where(Team.name == "Getafe")).one()
        t = Team(name="Atlético Madrid", country="England")
        s.add(t)
        s.flush()
        s.add(Fixture(competition_id=comp.id, home_team_id=getafe.id, away_team_id=t.id, kickoff_utc=ko,
                      match_date=ko.strftime("%Y-%m-%d"), first_seen_source="thesportsdb"))
        from fil.db import TeamAlias
        from fil.teamnames import normalize
        s.add(TeamAlias(alias_norm=normalize("Atlético Madrid"), source="thesportsdb",
                        team_id=s.scalars(select(Team).where(Team.name == "Ath Madrid")).one().id))  # alias already learnt
    assert merge_duplicates() == 1
    with session_scope() as s:
        assert len(s.scalars(select(Fixture)).all()) == 1


def test_merge_duplicates_with_identical_result_on_both(db):
    """Regression: the same source's identical result attached to both the duplicate and the real fixture."""
    from fil.ingest import merge_duplicates
    from fil.db import Competition

    ko = utcnow() - timedelta(days=1)
    ingest_records([rec("Getafe", "Ath Madrid", ko, status="finished", hg=0, ag=1)], "football_data_uk")
    ingest_records([rec("Getafe", "Atlético Madrid", ko, status="finished", hg=0, ag=1)], "thesportsdb")  # anchored
    with session_scope() as s:
        comp = s.scalars(select(Competition).where(Competition.code == "ENG1")).one()
        getafe = s.scalars(select(Team).where(Team.name == "Getafe")).one()
        t = Team(name="Atletico Madrid", country="England")
        s.add(t)
        s.flush()
        f = Fixture(competition_id=comp.id, home_team_id=getafe.id, away_team_id=t.id, kickoff_utc=ko,
                    match_date=ko.strftime("%Y-%m-%d"), first_seen_source="thesportsdb", status="finished")
        s.add(f)
        s.flush()
        s.add(ResultObservation(fixture_id=f.id, source="thesportsdb", status="finished", home_goals=0, away_goals=1))
    assert merge_duplicates() == 1
    with session_scope() as s:
        fx = s.scalars(select(Fixture)).one()
        assert fx.status == "finished" and not fx.result_conflict
        assert len(s.scalars(select(ResultObservation)).all()) == 2
